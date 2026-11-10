"""I/O sources for the parcel work list. Every fetcher fails soft."""
from __future__ import annotations

import asyncio
import logging

import httpx
from cachetools import TTLCache
from nkz_platform_sdk.crop_timeline import fetch_crop_timeline
from nkz_platform_sdk.crypto import generate_hmac_signature

from app.api.assessments import _history_points
from app.config import get_settings
from app.services.pipeline import _hmac_secret
from app.services.yield_forecast import parcel_urn, record_key

logger = logging.getLogger(__name__)

_AGRO_TIMEOUT_S = 5.0
# The weather service answers one parcel in a second or two, but a burst of simultaneous calls
# slows every one of them past the timeout. The list asks for all its parcels at once, so the
# calls are let through a few at a time and a good answer is reused for a short while.
_AGRO_MAX_CONCURRENT = 3
_AGRO_CACHE_TTL_S = 300
_agro_cache: TTLCache[tuple[str, str], dict] = TTLCache(maxsize=4096, ttl=_AGRO_CACHE_TTL_S)
_agro_gate: asyncio.Semaphore | None = None
_agro_gate_loop: asyncio.AbstractEventLoop | None = None


def _agro_semaphore() -> asyncio.Semaphore:
    """One gate per event loop (a semaphore cannot be shared across loops)."""
    global _agro_gate, _agro_gate_loop
    loop = asyncio.get_running_loop()
    if _agro_gate is None or _agro_gate_loop is not loop:
        _agro_gate, _agro_gate_loop = asyncio.Semaphore(_AGRO_MAX_CONCURRENT), loop
    return _agro_gate


async def fetch_timeline(tenant_id: str, parcel_urn_: str) -> dict | None:
    settings = get_settings()
    urn = parcel_urn(parcel_urn_)
    try:
        return await fetch_crop_timeline(
            tenant_id, urn, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context
        )
    except Exception as exc:  # noqa: BLE001 — the work list never fails on one source
        logger.warning("worklist: crop timeline failed tenant=%s parcel=%s: %s", tenant_id, urn, exc)
        return None


async def fetch_agro_status(tenant_id: str, parcel_short: str) -> dict | None:
    settings = get_settings()
    secret = _hmac_secret()
    if not settings.weather_daily_url or not secret:
        logger.warning("worklist: weather-api url or signing secret unset — no agro status")
        return None
    key = (tenant_id, parcel_short)
    cached = _agro_cache.get(key)
    if cached is not None:
        return cached
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-Auth-Signature": generate_hmac_signature(secret, "", tenant_id),
    }
    try:
        async with _agro_semaphore():
            cached = _agro_cache.get(key)  # answered while this call was waiting its turn
            if cached is not None:
                return cached
            async with httpx.AsyncClient(timeout=_AGRO_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{settings.weather_daily_url}/api/weather/parcel/{parcel_short}/agro-status",
                    headers=headers,
                )
        if resp.status_code != 200:
            logger.warning("worklist: agro-status HTTP %d tenant=%s parcel=%s",
                           resp.status_code, tenant_id, parcel_short)
            return None
        data = resp.json()
        if isinstance(data, dict):
            _agro_cache[key] = data  # only good answers are kept; a failure is retried next time
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("worklist: agro-status failed tenant=%s parcel=%s: %s", tenant_id, parcel_short, exc)
        return None


async def fetch_forecast(state, tenant_id: str, parcel_urn_: str) -> dict | None:
    urn = parcel_urn(parcel_urn_)
    try:
        return await state.get_json(record_key(tenant_id, urn))
    except Exception as exc:  # noqa: BLE001 — StoreError or unparsable record
        logger.warning("worklist: forecast read failed tenant=%s parcel=%s: %s", tenant_id, urn, exc)
        return None


async def fetch_history(request, parcel_short: str, days: int = 4) -> list[dict]:
    return await _history_points(request, parcel_short, days)


async def gather_parcel_inputs(request, state, tenant_id: str, parcel_short: str, *, with_history: bool) -> dict:
    urn = parcel_urn(parcel_short)
    names = ["timeline", "agro"]
    calls = [
        fetch_timeline(tenant_id, urn),
        fetch_agro_status(tenant_id, parcel_short),
    ]
    if state is not None:
        names.append("forecast")
        calls.append(fetch_forecast(state, tenant_id, urn))
    if with_history:
        names.append("history")
        calls.append(fetch_history(request, parcel_short))
    results = await asyncio.gather(*calls, return_exceptions=True)
    out: dict = {"timeline": None, "agro": None, "forecast": None, "history": []}
    for name, res in zip(names, results):
        if isinstance(res, BaseException):
            logger.warning("worklist: %s failed tenant=%s parcel=%s: %s", name, tenant_id, parcel_short, res)
            continue
        out[name] = res
    return out
