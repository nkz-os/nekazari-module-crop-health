"""In-season yield forecast for one parcel: stored record + on-demand refresh.

Mounted with the gateway identity dependency; the tenant always comes from
the verified identity (request.state.tenant_id).
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.redis_state import StoreError
from app.services.yield_forecast import (
    LOCK_TTL_S, compute_and_store, lock_key, parcel_urn, record_key,
)

logger = logging.getLogger(__name__)


def get_redis_state():
    """Late import: app.main imports this package."""
    from app.main import get_redis_state as _get

    return _get()

router = APIRouter(tags=["yield-forecast"])

_PARCEL_ID = re.compile(r"^(urn:ngsi-ld:AgriParcel:)?[A-Za-z0-9._:-]{1,128}$")


def _checked_urn(parcel_id: str) -> str:
    if not _PARCEL_ID.match(parcel_id):
        raise HTTPException(status_code=422, detail="invalid parcel id")
    return parcel_urn(parcel_id)


@router.get("/parcels/{parcel_id}/yield-forecast")
async def get_yield_forecast(parcel_id: str, request: Request):
    tenant = request.state.tenant_id
    state = get_redis_state()
    if not state.available:
        return {"status": "unavailable", "reason": "store_unavailable", "refreshing": False}
    urn = _checked_urn(parcel_id)
    try:
        record = await state.get_json(record_key(tenant, urn))
    except StoreError:
        return {"status": "unavailable", "reason": "store_unavailable", "refreshing": False}
    refreshing = await state.is_locked(lock_key(tenant, urn))
    if record is None:
        return {"status": "not_computed", "refreshing": refreshing}
    return {**record, "refreshing": refreshing}


async def _refresh(state, tenant: str, urn: str) -> None:
    try:
        outcome = await compute_and_store(state, tenant, urn, hold_lock=False, retry=True)
        logger.info("yield_forecast refresh tenant=%s parcel=%s outcome=%s", tenant, urn, outcome)
    except Exception:
        logger.exception("yield_forecast refresh failed tenant=%s parcel=%s", tenant, urn)
    finally:
        await state.unlock(lock_key(tenant, urn))


@router.post("/parcels/{parcel_id}/yield-forecast/refresh", status_code=202)
async def refresh_yield_forecast(parcel_id: str, request: Request, background: BackgroundTasks):
    tenant = request.state.tenant_id
    urn = _checked_urn(parcel_id)
    state = get_redis_state()
    got = await state.try_lock(lock_key(tenant, urn), LOCK_TTL_S)
    if got is None:
        return JSONResponse(status_code=503, content={"refreshing": False, "reason": "store_unavailable"})
    if got:
        background.add_task(_refresh, state, tenant, urn)
    return {"refreshing": True}
