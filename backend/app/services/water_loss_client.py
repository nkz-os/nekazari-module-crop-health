"""Client for bioorch's water-loss-by-stage estimate (planning contract 2.x).

One request per call, no polling: the screen polls this relay. Transport and
contract problems become a synthesized failed answer, never an exception.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_CONTRACT_MAJOR = "2"


def _failed(code: str) -> dict:
    return {"state": "failed",
            "unavailable": [{"provider_id": "aquacrop", "reason": "request_failed", "code": code}]}


async def fetch_water_loss(parcel_urn: str, tenant_id: str, *, retry: bool = False) -> dict | None:
    """Answer dict, a synthesized failed dict, or None when bioorch says 404 (unknown parcel)."""
    settings = get_settings()
    url = (f"{settings.bioorchestrator_url}/api/graph/planning/parcels/"
           f"{quote(parcel_urn, safe='')}/estimates/water-loss-by-stage")
    headers = {"X-Internal-Service-Secret": settings.internal_service_secret,
               "X-Tenant-ID": tenant_id, "X-User-ID": "crop-health-worker"}
    params = {"retry": "true"} if retry else {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        logger.warning("water_loss request failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        return _failed(type(exc).__name__)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.warning("water_loss http %s tenant=%s parcel=%s", resp.status_code, tenant_id, parcel_urn)
        return _failed(str(resp.status_code))
    try:
        answer = resp.json()
    except ValueError:
        logger.warning("water_loss invalid json tenant=%s parcel=%s", tenant_id, parcel_urn)
        return _failed("invalid_json")
    if not isinstance(answer, dict):
        logger.warning("water_loss non-object json tenant=%s parcel=%s", tenant_id, parcel_urn)
        return _failed("invalid_json")
    if str(answer.get("contract_version", "")).split(".")[0] != _CONTRACT_MAJOR:
        logger.warning("water_loss contract mismatch %s tenant=%s parcel=%s",
                       answer.get("contract_version"), tenant_id, parcel_urn)
        return _failed("contract_mismatch")
    return answer
