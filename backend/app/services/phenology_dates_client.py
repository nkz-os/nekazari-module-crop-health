"""Client for bioorch's milestone dates (planning contract 2.x).

One synchronous GET. Transport problems, an unknown endpoint (older
deployment) and a contract-major mismatch become a synthesized answer, never
an exception, so the caller's store rules decide what to keep.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PROVIDER_ID = "aquacrop_calendar"
_CONTRACT_MAJOR = "2"
_TOTAL_TIMEOUT_S = 15.0  # one budget for the whole call (connect, send, read), not per phase


def _answer(state: str, reason: str, code: str) -> dict:
    return {"state": state,
            "unavailable": [{"provider_id": PROVIDER_ID, "reason": reason, "code": code}]}


async def fetch_phenology_dates(parcel_urn: str, tenant_id: str) -> dict:
    settings = get_settings()
    url = (f"{settings.bioorchestrator_url}/api/graph/planning/parcels/"
           f"{quote(parcel_urn, safe='')}/phenology")
    headers = {"X-Internal-Service-Secret": settings.internal_service_secret,
               "X-Tenant-ID": tenant_id, "X-User-ID": "crop-health-worker"}
    try:
        async with httpx.AsyncClient(timeout=_TOTAL_TIMEOUT_S) as client:
            resp = await asyncio.wait_for(client.get(url, headers=headers), timeout=_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("phenology_dates timed out after %ss tenant=%s parcel=%s",
                       _TOTAL_TIMEOUT_S, tenant_id, parcel_urn)
        return _answer("failed", "request_failed", "timeout")
    except httpx.HTTPError as exc:
        logger.warning("phenology_dates request failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        return _answer("failed", "request_failed", type(exc).__name__)
    if resp.status_code == 404:
        logger.info("phenology_dates endpoint or parcel unknown tenant=%s parcel=%s", tenant_id, parcel_urn)
        return _answer("unavailable", "endpoint_unavailable", "404")
    if resp.status_code != 200:
        logger.warning("phenology_dates http %s tenant=%s parcel=%s", resp.status_code, tenant_id, parcel_urn)
        return _answer("failed", "request_failed", str(resp.status_code))
    try:
        answer = resp.json()
    except ValueError:
        return _answer("failed", "request_failed", "invalid_json")
    if not isinstance(answer, dict):
        return _answer("failed", "request_failed", "invalid_json")
    if str(answer.get("contract_version", "")).split(".")[0] != _CONTRACT_MAJOR:
        logger.warning("phenology_dates contract mismatch %s tenant=%s parcel=%s",
                       answer.get("contract_version"), tenant_id, parcel_urn)
        return _answer("failed", "request_failed", "contract_mismatch")
    return answer
