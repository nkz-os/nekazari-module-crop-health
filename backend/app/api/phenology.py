"""Read-only phenology-status endpoint (keel contract) + explicit sync.

STRICT CQRS split:
- GET  /parcels/{parcel_id}/phenology-status        — READ-ONLY. Reads the
  latest stored CropHealthAssessment from Orion and projects the stage
  timeline on the fly. MUST NOT write to Orion — polling/page-reloads must
  never amplify writes.
- POST /parcels/{parcel_id}/phenology-status/sync   — explicit recompute.
  Calls ``compute_assessment`` (which performs the Orion write) and returns
  the freshly computed status.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Request

from app.services import context_client
from app.services.pipeline import compute_assessment

logger = logging.getLogger(__name__)
router = APIRouter(tags=["phenology"])

_MEAN_DAILY_GDD_DEFAULT = 8.0  # Mediterranean default mean daily GDD


async def _read_latest_assessment(parcel_id: str, tenant_id: str) -> dict | None:
    """Latest CropHealthAssessment for the parcel from Orion (read-only).

    Pure query — never upserts/patches/deletes. Fail-safe: returns ``None``
    on any error so the GET handler degrades to ``{"status": "pending"}``
    instead of 500ing.
    """
    from app.config import get_settings
    from nkz_platform_sdk.orion import OrionClient

    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        parcel_short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
        rows = await client.query_entities(
            type="CropHealthAssessment",
            q=f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_short}"',
            limit=1,
            options="keyValues",
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001 — fail-safe, read-only path must never 500
        logger.warning("_read_latest_assessment failed for %s: %s", parcel_id, exc)
        return None
    finally:
        await client.close()


def _unwrap(value):
    """NGSI-LD keyValues already unwraps Property values, but guard for the
    occasional full-format leftover (``{"type": "Property", "value": ...}``)."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _build_status_from_dict(latest: dict, thresholds: dict[str, tuple[float, float]]) -> dict:
    """Project the phenology status from a serialised assessment (dict)."""
    from app.engines.phenology_progress import project_stage_timeline

    gdd = _unwrap(latest.get("gddAccumulated"))
    today = date.today()
    stages = (
        project_stage_timeline(float(gdd), thresholds, _MEAN_DAILY_GDD_DEFAULT, today)
        if gdd is not None and thresholds
        else []
    )
    parcel_ref = latest.get("hasAgriParcel")
    if isinstance(parcel_ref, dict):
        parcel_ref = parcel_ref.get("object")

    return {
        "parcelId": parcel_ref,
        "asOf": today.isoformat(),
        "seasonStart": _unwrap(latest.get("seasonStart")),
        "currentStage": _unwrap(latest.get("phenologyStage")) or "unknown",
        "gdd": {"accumulated": float(gdd)} if gdd is not None else None,
        "dataFidelity": _unwrap(latest.get("dataFidelity")) or "regional_proxy",
        "stages": stages,
    }


def _build_status_from_assessment(assessment, thresholds: dict[str, tuple[float, float]]) -> dict:
    """Project the phenology status from a live ``CropHealthAssessment`` model."""
    from app.engines.phenology_progress import project_stage_timeline

    gdd = assessment.gdd_accumulated
    today = date.today()
    stages = (
        project_stage_timeline(gdd, thresholds, _MEAN_DAILY_GDD_DEFAULT, today)
        if gdd is not None and thresholds
        else []
    )
    return {
        "parcelId": assessment.parcel_id,
        "asOf": today.isoformat(),
        "seasonStart": None,
        "currentStage": assessment.phenology_stage or "unknown",
        "gdd": {"accumulated": gdd} if gdd is not None else None,
        "dataFidelity": assessment.data_fidelity,
        "stages": stages,
    }


@router.get("/parcels/{parcel_id}/phenology-status")
async def phenology_status(parcel_id: str, request: Request):
    """Read-only phenology status. Never writes to Orion.

    Reads the latest stored CropHealthAssessment (a query) and projects the
    stage timeline on the fly using the cached/fallback phenology thresholds.
    Fail-safe: returns ``{"status": "pending"}`` when there is no assessment
    yet (never 500s).
    """
    tenant_id = getattr(request.state, "tenant_id", "") or request.headers.get("X-Tenant-ID", "")
    latest = await _read_latest_assessment(parcel_id, tenant_id)
    if latest is None:
        return {"status": "pending", "parcelId": parcel_id}

    species = _unwrap(latest.get("species")) or _unwrap(latest.get("cropSpecies")) or "generic"
    thresholds = await context_client.get_phenology_stages(species)
    return _build_status_from_dict(latest, thresholds)


@router.post("/parcels/{parcel_id}/phenology-status/sync")
async def phenology_status_sync(parcel_id: str, request: Request):
    """Explicit recompute. Forces a fresh ``compute_assessment`` (Orion write).

    This is the ONLY write path for phenology status — the GET handler above
    never calls this. Fail-safe: returns ``{"status": "no_crop"}`` when the
    parcel has no assigned crop (never 500s).
    """
    tenant_id = getattr(request.state, "tenant_id", "") or request.headers.get("X-Tenant-ID", "")
    assessment = await compute_assessment(parcel_id, tenant_id)
    if assessment is None:
        return {"status": "no_crop", "parcelId": parcel_id}

    species = assessment.crop_species or "generic"
    thresholds = await context_client.get_phenology_stages(species)
    return _build_status_from_assessment(assessment, thresholds)
