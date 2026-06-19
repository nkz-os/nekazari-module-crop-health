"""Internal endpoint: parcel activation lifecycle for crop-health.

Called by entity-manager with X-Internal-Service-Secret when a user activates
crop-health for a parcel. Frozen contract:
POST /api/crop-health/internal/setup-parcel
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nkz_platform_sdk.activation import ModuleActivation
from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings
from app.services.pipeline import compute_assessment

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
    action: str = "activate"  # "activate" | "deactivate"


@router.post("/setup-parcel", status_code=201)
async def setup_parcel(request: Request, body: SetupParcelRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
        logger.warning("Unauthorized internal setup-parcel call from %s", request.client)
        raise HTTPException(status_code=401, detail="Unauthorized")
    if body.action not in ("activate", "deactivate"):
        raise HTTPException(status_code=400, detail="Invalid action")

    parcel_urn = body.parcel_id
    if not parcel_urn.startswith("urn:ngsi-ld:AgriParcel:"):
        parcel_urn = f"urn:ngsi-ld:AgriParcel:{parcel_urn}"

    if body.action == "deactivate":
        logger.info("Deactivated crop-health for parcel %s", parcel_urn)
        return {"message": "deactivated", "parcel_id": body.parcel_id}

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
        subscriptions=[{"type": "DeviceMeasurement", "throttling": 30}],
        module_name="crop-health",
        context_url=settings.orion_ld_context,
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
    offset = int(cursor) if cursor else 0
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


@router.post("/run-scheduled-assessments")
async def run_scheduled_assessments(request: Request, body: ScheduledRunRequest):
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
        logger.warning(
            "Unauthorized internal run-scheduled-assessments call from %s", request.client
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    ids, next_cursor = await _list_active_crop_parcels(
        body.tenant_id, body.cursor, body.batch_size
    )
    written, errors = 0, []
    for parcel_id in ids:
        try:
            result = await compute_assessment(parcel_id, body.tenant_id)
            if result is not None:
                written += 1
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
