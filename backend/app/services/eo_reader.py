"""Satellite observations for crop-health, read with the platform SDK.

Every reader of satellite products goes through ``observations``: it calls
``fetch_eo_observations`` once per target (a parcel without its zones, or one
zone), in both stored shapes, and keeps the answer for a few minutes so one
assessment asks the broker once per target however many values it needs. The
readers pick from that list in memory with ``pick`` and ``newest``.

A failed read raises and is never cached; each reader decides what "no data"
means for it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Collection, Iterable
from datetime import date

from nkz_platform_sdk import EO_FAMILIES, EO_VALUE_NAMES, EOObservation, fetch_eo_observations

logger = logging.getLogger(__name__)

# Families each reader accepts. NDVI is single-scene optical only: a composite
# covers several scenes and is dated by the last one, so it would shift a series.
NDVI_FAMILIES = frozenset({"s2-indices"})
LST_FAMILIES = frozenset({"landsat-lst", "clms-lst"})
SMI_FAMILIES = frozenset({"s1-soil-moisture"})
SAR_FAMILIES = frozenset({"s1-backscatter"})
NDVI = "ndvi"
LST = "lst"
SMI = "soilMoistureIndex"
VV = "backscatterVV"
VH = "backscatterVH"
USED_FAMILIES = NDVI_FAMILIES | LST_FAMILIES | SMI_FAMILIES | SAR_FAMILIES
USED_NAMES = frozenset({NDVI, LST, SMI, VV, VH})
if not (USED_FAMILIES <= set(EO_FAMILIES) and USED_NAMES <= set(EO_VALUE_NAMES)):
    raise RuntimeError("eo_reader: a family or value name is not in the SDK vocabulary")

# ASSUMPTION: products arrive at most daily, so a reading up to 5 minutes old is current enough
# for every reader (assessments and the source panel alike).
_CACHE_TTL_S = 300.0
_CACHE_MAX = 512
_cache: OrderedDict[tuple[str, str], tuple[float, list[EOObservation]]] = OrderedDict()
_inflight: dict[tuple[str, str], asyncio.Task] = {}


def parcel_urn(parcel_id: str) -> str:
    return f"urn:ngsi-ld:AgriParcel:{parcel_id}"


def clear_cache() -> None:
    _cache.clear()
    _inflight.clear()


async def _fetch(tenant_id: str, *, parcel_id: str | None, zone_urn: str | None) -> list[EOObservation]:
    from app.config import get_settings
    from nkz_platform_sdk.orion import OrionClient

    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        if zone_urn:
            return await fetch_eo_observations(client, zone_id=zone_urn)
        return await fetch_eo_observations(client, parcel_id=parcel_urn(parcel_id))
    finally:
        await client.close()


async def observations(
    tenant_id: str, *, parcel_id: str | None = None, zone_urn: str | None = None,
) -> list[EOObservation]:
    """All satellite observations of a parcel (zones left out) or of one zone, oldest first."""
    if bool(parcel_id) == bool(zone_urn):
        raise ValueError("pass parcel_id or zone_urn")
    key = (tenant_id, zone_urn or parcel_urn(parcel_id))
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        _cache.move_to_end(key)
        return hit[1]
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_fetch(tenant_id, parcel_id=parcel_id, zone_urn=zone_urn))
        _inflight[key] = task
    try:
        result = await asyncio.shield(task)
    finally:
        if _inflight.get(key) is task and task.done():
            _inflight.pop(key, None)
    _cache[key] = (time.monotonic() + _CACHE_TTL_S, result)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return result


def pick(
    obs: Iterable[EOObservation],
    *,
    families: Collection[str],
    require: Collection[str],
    since: date | None = None,
) -> list[EOObservation]:
    """Observations of ``families`` that carry every ``require`` value, from ``since`` on, oldest first."""
    out = [
        o for o in obs
        if o.family in families
        and all(o.values.get(name) is not None for name in require)
        and (since is None or o.sensing_day >= since)
    ]
    return sorted(out, key=_order)


def newest(
    obs: Iterable[EOObservation],
    *,
    families: Collection[str],
    require: Collection[str],
    since: date | None = None,
) -> EOObservation | None:
    """The most recent observation ``pick`` keeps, across the families (None if none)."""
    kept = pick(obs, families=families, require=require, since=since)
    return kept[-1] if kept else None


def number(o: EOObservation, name: str) -> float | None:
    """A value as ``float``; None if absent or not numeric."""
    v = o.values.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _order(o: EOObservation) -> tuple:
    return (o.sensing_day, o.sensing_time is not None, o.sensing_time or 0, o.entity_id)
