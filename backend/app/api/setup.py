"""Internal endpoint: parcel activation lifecycle for crop-health.

Called by entity-manager with X-Internal-Service-Secret when a user activates
crop-health for a parcel. Frozen contract:
POST /api/crop-health/internal/setup-parcel
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nkz_platform_sdk.activation import ModuleActivation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

INTERNAL_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

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
    return {
        "message": "activated",
        "parcel_id": body.parcel_id,
        "created": result["created"],
        "skipped": result["skipped"],
        "entity_ids": result["entity_ids"],
    }
