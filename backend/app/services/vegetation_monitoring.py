"""Client for vegetation's satellite-monitoring state (internal API).

Optional enrichment: any problem (feature off, transport, HTTP error, bad body)
returns None and logs a warning, so callers show nothing new instead of failing.
The feature is off while `vegetation_internal_url` is empty.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT_S = 3.0  # optional enrichment: a slow vegetation must not slow the callers down
CANDIDATES_TTL_S = 300.0
FAILURE_TTL_S = 60.0  # after an outage-like failure, do not ask again for a minute

# tenant -> (monotonic time of the read, parcel URNs with a crop and no monitoring)
_candidates_cache: dict[str, tuple[float, set[str]]] = {}
# tenant -> monotonic time until which vegetation is not asked (negative cache)
_down_until: dict[str, float] = {}


def _monotonic() -> float:
    return time.monotonic()


async def _get_json(path: str, tenant_id: str, what: str) -> dict | None:
    settings = get_settings()
    base = (settings.vegetation_internal_url or "").rstrip("/")
    if not base:
        return None
    if _down_until.get(tenant_id, 0.0) > _monotonic():
        return None
    headers = {"X-Internal-Service-Secret": settings.internal_service_secret}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(f"{base}{path}", params={"tenant_id": tenant_id}, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("vegetation monitoring %s request failed tenant=%s: %s", what, tenant_id,
                       type(exc).__name__)
        _down_until[tenant_id] = _monotonic() + FAILURE_TTL_S
        return None
    if resp.status_code != 200:
        logger.warning("vegetation monitoring %s http %s tenant=%s", what, resp.status_code, tenant_id)
        if resp.status_code >= 500:
            _down_until[tenant_id] = _monotonic() + FAILURE_TTL_S
        return None
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        logger.warning("vegetation monitoring %s invalid body tenant=%s", what, tenant_id)
        return None
    return body


async def parcel_monitoring(tenant_id: str, parcel_urn: str) -> dict | None:
    """Vegetation's `monitoring_state` of one parcel, or None when unknown."""
    path = f"/api/internal/vegetation/parcels/{quote(parcel_urn, safe='')}/monitoring"
    return await _get_json(path, tenant_id, "state")


async def tenant_candidates(tenant_id: str) -> set[str] | None:
    """URNs of the tenant's parcels with a living crop and no monitoring; None when unknown.

    Cached 5 minutes per tenant; a failure is remembered for 60 s (see `_get_json`).
    """
    now = _monotonic()
    hit = _candidates_cache.get(tenant_id)
    if hit and now - hit[0] < CANDIDATES_TTL_S:
        return hit[1]
    body = await _get_json("/api/internal/vegetation/monitoring/candidates", tenant_id, "candidates")
    if body is None:
        return None
    rows = body.get("candidates")
    if not isinstance(rows, list):
        logger.warning("vegetation monitoring candidates invalid body tenant=%s", tenant_id)
        return None
    urns = {r["entity_id"] for r in rows if isinstance(r, dict) and r.get("entity_id")}
    _candidates_cache[tenant_id] = (now, urns)
    return urns
