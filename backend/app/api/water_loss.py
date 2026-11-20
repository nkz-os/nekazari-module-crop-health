"""Water loss by growth stage for one parcel: relay of bioorch's estimate (nothing stored).

Mounted with the gateway identity dependency; the tenant always comes from
the verified identity (request.state.tenant_id).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.yield_forecast import _checked_urn
from app.services.water_loss_client import fetch_water_loss

router = APIRouter(tags=["water-loss"])


@router.get("/parcels/{parcel_id}/water-loss-by-stage")
async def get_water_loss_by_stage(parcel_id: str, request: Request, retry: bool = False):
    tenant = request.state.tenant_id
    urn = _checked_urn(parcel_id)
    answer = await fetch_water_loss(urn, tenant, retry=retry)
    if answer is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    return answer
