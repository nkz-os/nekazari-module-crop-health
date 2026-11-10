"""Internal endpoint: parcel activation lifecycle for crop-health.

Called by entity-manager with X-Internal-Service-Secret when a user activates
crop-health for a parcel. Frozen contract:
POST /api/crop-health/internal/setup-parcel
"""

import hmac
import logging
import re
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nkz_platform_sdk.activation import ModuleActivation
from nkz_platform_sdk.notify_auth import derived_tokens_from_env
from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings
from app.services import weekly_report
from app.services import phenology_dates
from app.services.pipeline import compute_assessment
from app.services.work_alerts import emit_work_alerts
from app.services.yield_forecast import compute_and_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

INTERNAL_SECRET = get_settings().internal_service_secret

# Entities owned by crop-health (design spec §3.3)
PLACEHOLDER_ENTITIES = [
    {"type": "AgriCrop", "id_suffix": "default"},
    {"type": "CropHealthAssessment", "id_suffix": "latest"},
]


class SetupParcelRequest(BaseModel):
    parcel_id: str
    tenant_id: str
    parcel_name: str = ""
    action: str = "activate"  # "activate" | "deactivate" | "teardown"


@router.post("/setup-parcel", status_code=201)
async def setup_parcel(request: Request, body: SetupParcelRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or not hmac.compare_digest(secret.encode(), INTERNAL_SECRET.encode()):
        logger.warning("Unauthorized internal setup-parcel call from %s", request.client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    if body.action not in ("activate", "deactivate", "teardown"):
        raise HTTPException(status_code=400, detail="Invalid action")

    parcel_urn = body.parcel_id
    if not parcel_urn.startswith("urn:ngsi-ld:AgriParcel:"):
        parcel_urn = f"urn:ngsi-ld:AgriParcel:{parcel_urn}"

    if body.action == "deactivate":
        logger.info("Deactivated crop-health for parcel %s", parcel_urn)
        return {"message": "deactivated", "parcel_id": body.parcel_id}
    if body.action == "teardown":
        logger.info("Teardown of crop-health for parcel %s", parcel_urn)
        return {"message": "torn_down", "parcel_id": body.parcel_id}

    activation = ModuleActivation(tenant_id=body.tenant_id)
    try:
        result = await activation.ensure_entities(
            parcel_id=parcel_urn, entities=PLACEHOLDER_ENTITIES
        )
    finally:
        await activation.close()

    logger.info(
        "setup-parcel %s tenant=%s: created=%d skipped=%d errors=%d",
        body.parcel_id, body.tenant_id,
        result["created"], result["skipped"], len(result["errors"]),
    )
    if result["errors"] and not (result["created"] or result["skipped"]):
        raise HTTPException(
            status_code=502,
            detail=f"Orion-LD entity creation failed: {result['errors'][:3]}",
        )

    settings = get_settings()
    notification_url = f"{settings.self_url}{settings.api_prefix}/webhooks/fiware-sensors"
    registrar = SubscriptionRegistrar(
        orion_url=settings.orion_ld_url,
        notification_url=notification_url,
        subscriptions=[{"type": "DeviceMeasurement", "throttling": None}],
        module_name="crop-health",
        context_url=settings.orion_ld_context,
        # The registrar owns the receiver auth header: the master secret (legacy) or,
        # with NKZ_NOTIFY_DERIVED_TOKENS on, a token bound to the tenant and this
        # receiver so the broker never stores the master.
        internal_secret=INTERNAL_SECRET or None,
        derived_tokens=bool(INTERNAL_SECRET) and derived_tokens_from_env(),
    )
    sub_result = await registrar.ensure_all([body.tenant_id])
    logger.info(
        "setup-parcel subscription ensure tenant=%s: created=%d skipped=%d errors=%d",
        body.tenant_id, sub_result["created"], sub_result["skipped"], len(sub_result["errors"]),
    )

    return {
        "message": "activated",
        "parcel_id": body.parcel_id,
        "created": result["created"],
        "skipped": result["skipped"],
        "entity_ids": result["entity_ids"],
    }


class ScheduledRunRequest(BaseModel):
    tenant_id: str
    cursor: str | None = None
    batch_size: int = 200


async def _list_active_crop_parcels(tenant_id: str, cursor: str | None, batch_size: int):
    """One bounded page of AgriParcel with an active hasAgriCrop. Returns (ids, next_cursor)."""
    from nkz_platform_sdk.orion import OrionClient

    settings = get_settings()
    # Never 500 on a malformed cursor: coerce a non-numeric/negative cursor to
    # offset 0 rather than letting int() raise before the per-parcel loop.
    try:
        offset = int(cursor) if cursor else 0
        if offset < 0:
            offset = 0
    except (TypeError, ValueError):
        logger.warning("run-scheduled-assessments: non-numeric cursor %r — offset 0", cursor)
        offset = 0
    # Clamp batch size to a sane maximum to bound Orion query cost.
    batch_size = min(max(int(batch_size), 1), 500)
    client = OrionClient(
        tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context
    )
    try:
        rows = await client.query_entities(
            type="AgriParcel",
            q="hasAgriCrop",
            limit=batch_size,
            offset=offset,
            options="keyValues",
        )
    finally:
        await client.close()
    ids = [r["id"] for r in rows]
    next_cursor = str(offset + batch_size) if len(ids) == batch_size else None
    return ids, next_cursor


_DATES_MAX_CONSECUTIVE_FAILURES = 3


async def _refresh_phenology_dates(tenant_id: str, parcel_id: str, species: str | None) -> str | None:
    """Cereal-calendar milestone dates for the parcel; returns the outcome word, or None when not attempted.

    Never raises and never changes the run's result.
    """
    if not species:
        return None
    try:
        from app.main import get_redis_state

        try:
            state = get_redis_state()
        except RuntimeError:
            state = None
        return await phenology_dates.refresh(state, tenant_id, parcel_id, species)
    except Exception:  # noqa: BLE001 — the assessment run continues
        logger.exception("run-scheduled-assessments: phenology dates failed tenant=%s parcel=%s",
                         tenant_id, parcel_id)
        return "error"


@router.post("/run-scheduled-assessments")
async def run_scheduled_assessments(request: Request, body: ScheduledRunRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or not hmac.compare_digest(secret.encode(), INTERNAL_SECRET.encode()):
        logger.warning(
            "Unauthorized internal run-scheduled-assessments call from %s", request.client
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    ids, next_cursor = await _list_active_crop_parcels(
        body.tenant_id, body.cursor, body.batch_size
    )
    written, errors = 0, []
    dates_failures, dates_attempted, dates_stopped = 0, 0, False
    for parcel_id in ids:
        try:
            result = await compute_assessment(parcel_id, body.tenant_id)
            if result is not None:
                written += 1
                if not dates_stopped:
                    outcome = await _refresh_phenology_dates(
                        body.tenant_id, parcel_id, getattr(result, "crop_species", None))
                    if outcome in ("failed", "error"):
                        dates_attempted += 1
                        dates_failures += 1
                        if dates_failures >= _DATES_MAX_CONSECUTIVE_FAILURES:
                            dates_stopped = True
                            logger.warning(
                                "run-scheduled-assessments: stopping phenology dates for the rest of the batch "
                                "tenant=%s consecutive_failures=%d attempted=%d",
                                body.tenant_id, dates_failures, dates_attempted)
                    elif outcome not in (None, "not_calendar"):
                        dates_attempted += 1
                        dates_failures = 0
        except Exception as exc:  # noqa: BLE001 — isolate per parcel, never abort the batch
            logger.exception(
                "run-scheduled-assessments: parcel %s tenant=%s failed",
                parcel_id, body.tenant_id,
            )
            errors.append({"parcel": parcel_id, "error": str(exc)[:200]})

    return {
        "processed": len(ids),
        "written": written,
        "errors": errors,
        "next_cursor": next_cursor,
    }




class YieldForecastRunRequest(BaseModel):
    tenant_id: str
    cursor: str | None = None
    batch_size: int = 1


async def _list_all_parcels(tenant_id: str, cursor: str | None, batch_size: int):
    """One page of every AgriParcel (cadastral and hand-drawn alike).

    No crop filter: bioorch resolves the crop from the crop cycle and answers
    unavailable at once for an unsown parcel (spec §4.3).
    """
    from nkz_platform_sdk.orion import OrionClient

    settings = get_settings()
    try:
        offset = max(int(cursor), 0) if cursor else 0
    except (TypeError, ValueError):
        offset = 0
    batch_size = min(max(int(batch_size), 1), 20)
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        # No attrs: in NGSI-LD it also filters out entities lacking them.
        rows = await client.query_entities(type="AgriParcel", limit=batch_size, offset=offset,
                                           options="keyValues")
    finally:
        await client.close()
    ids = [r["id"] for r in rows]
    return ids, (str(offset + batch_size) if len(ids) == batch_size else None)


@router.post("/run-yield-forecasts")
async def run_yield_forecasts(request: Request, body: YieldForecastRunRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or not hmac.compare_digest(secret.encode(), INTERNAL_SECRET.encode()):
        logger.warning("Unauthorized internal run-yield-forecasts call from %s", request.client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    from app.main import get_redis_state

    state = get_redis_state()
    ids, next_cursor = await _list_all_parcels(body.tenant_id, body.cursor, body.batch_size)
    written, errors = 0, []
    for parcel_id in ids:
        try:
            outcome = await compute_and_store(state, body.tenant_id, parcel_id)
        except Exception as exc:
            logger.exception("run-yield-forecasts tenant=%s parcel=%s failed", body.tenant_id, parcel_id)
            errors.append({"parcel_id": parcel_id, "error": type(exc).__name__})
            continue
        if outcome == "written":
            written += 1
        elif outcome == "store_error":
            errors.append({"parcel_id": parcel_id, "error": "store_error"})
    return {"processed": len(ids), "written": written, "errors": errors, "next_cursor": next_cursor}


class WorkAlertsRunRequest(BaseModel):
    tenant_id: str


@router.post("/work-alerts/run")
async def run_work_alerts(request: Request, body: WorkAlertsRunRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or not hmac.compare_digest(secret.encode(), INTERNAL_SECRET.encode()):
        logger.warning("Unauthorized internal work-alerts call from %s", request.client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return await emit_work_alerts(body.tenant_id)
    except Exception as exc:  # noqa: BLE001 — surface as 502 so the CronJob logs and counts it
        logger.exception("work-alerts tenant=%s failed", body.tenant_id)
        raise HTTPException(status_code=502, detail=type(exc).__name__) from exc


_TENANT_RE = re.compile(r"^[a-z0-9_-]+$")


@router.get("/weekly-report")
async def weekly_report_contribution(request: Request, tenant_id: str = "", week_start: str = ""):
    """Tasks, changes and figures for the tenant's weekly report (contract version 1)."""
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or not hmac.compare_digest(secret.encode(), INTERNAL_SECRET.encode()):
        logger.warning("Unauthorized internal weekly-report call from %s", request.client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not _TENANT_RE.fullmatch(tenant_id):
        raise HTTPException(status_code=400, detail="invalid tenant_id")
    try:
        start = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid week_start") from None
    if start.weekday() != 0:
        raise HTTPException(status_code=400, detail="week_start must be a Monday")
    try:
        return await weekly_report.build(tenant_id, start)
    except Exception as exc:  # noqa: BLE001 — an outage is a failure, never an empty report
        logger.exception("weekly-report tenant=%s failed", tenant_id)
        raise HTTPException(status_code=502, detail=type(exc).__name__) from exc
