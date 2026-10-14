"""Client for bioorch's in-season forecast (planning contract 2.x, C4).

The first call starts the day's job or joins it; then poll with job_id until it
settles. Transport problems become a synthesized failed answer, never an
exception, so the caller's store rules decide what to keep.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_SETTLED = {"done", "failed", "unavailable"}
_CONTRACT_MAJOR = "2"


def _failed(code: str) -> dict:
    return {"state": "failed",
            "unavailable": [{"provider_id": "aquacrop", "reason": "request_failed", "code": code}]}


async def fetch_in_season(parcel_urn: str, tenant_id: str, *, poll_interval: float = 5.0,
                          timeout: float = 240.0, retry: bool = False) -> dict:
    """retry=True asks bioorch to rerun a job that already failed today (user refresh)."""
    settings = get_settings()
    url = (f"{settings.bioorchestrator_url}/api/graph/planning/parcels/"
           f"{quote(parcel_urn, safe='')}/estimates/in-season")
    headers = {"X-Internal-Service-Secret": settings.internal_service_secret,
               "X-Tenant-ID": tenant_id, "X-User-ID": "crop-health-worker"}
    deadline = time.monotonic() + timeout
    params: dict[str, str] = {"retry": "true"} if retry else {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                resp = await client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                logger.warning("in_season request failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
                return _failed(type(exc).__name__)
            if resp.status_code != 200:
                logger.warning("in_season http %s tenant=%s parcel=%s", resp.status_code, tenant_id, parcel_urn)
                return _failed(str(resp.status_code))
            try:
                answer = resp.json()
            except ValueError:
                return _failed("invalid_json")
            if str(answer.get("contract_version", "")).split(".")[0] != _CONTRACT_MAJOR:
                logger.warning("in_season contract mismatch %s", answer.get("contract_version"))
                return _failed("contract_mismatch")
            if answer.get("state") in _SETTLED or time.monotonic() >= deadline:
                return answer
            if answer.get("job_id"):
                params = {"job_id": answer["job_id"]}
            await asyncio.sleep(poll_interval)
