"""Satellite observations for crop-health, read with the platform SDK.

Every reader of satellite products goes through ``observations``: it calls
``fetch_eo_observations`` once per target (a parcel without its zones, or one
zone), in both stored shapes, and keeps the answer for a few minutes so one
assessment asks the broker once per target however many values it needs. The
readers pick from that list in memory with ``pick`` and ``newest``.

A failed read raises and is never cached; each reader decides what "no data"
means for it. Every reader of that target sees the same failure, so a broker
error leaves all of them without data until the next read succeeds.
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
# covers several scenes, dated by its first scene in the earlier stored shape and
# by the last day of its window in the SDM shape, so it would shift a series.
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
# Bounded memory: only the values the readers use are kept, for at most this many targets.
_CACHE_MAX = 64
_cache: OrderedDict[tuple[str, str], tuple[float, list[EOObservation]]] = OrderedDict()
_inflight: dict[tuple[str, str], asyncio.Task] = {}
_generation = 0  # bumped by clear_cache: a read started before it is not stored


def parcel_urn(parcel_id: str) -> str:
    return f"urn:ngsi-ld:AgriParcel:{parcel_id}"


def clear_cache() -> None:
    global _generation
    _generation += 1
    _cache.clear()
    _inflight.clear()


async def _fetch(tenant_id: str, *, parcel_id: str | None, zone_urn: str | None) -> list[EOObservation]:
    from app.config import get_settings
    from nkz_platform_sdk.orion import OrionClient

    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        if zone_urn:
            return await fetch_eo_observations(client, zone_id=zone_urn, names=USED_NAMES)
        return await fetch_eo_observations(client, parcel_id=parcel_urn(parcel_id), names=USED_NAMES)
    finally:
        await client.close()


async def observations(
    tenant_id: str, *, parcel_id: str | None = None, zone_urn: str | None = None,
) -> list[EOObservation]:
    """All satellite observations of a parcel (zones left out) or of one zone, oldest first."""
    if bool(parcel_id) == bool(zone_urn):
        raise ValueError("pass parcel_id or zone_urn")
    key = (tenant_id, zone_urn or parcel_urn(parcel_id))
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        _cache.move_to_end(key)
        return hit[1]
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_fetch(tenant_id, parcel_id=parcel_id, zone_urn=zone_urn))
        _inflight[key] = task
        # The read settles itself, even when every caller was cancelled meanwhile.
        task.add_done_callback(lambda t, k=key, g=_generation: _settle(k, t, g))
    return await asyncio.shield(task)


def _settle(key: tuple[str, str], task: asyncio.Task, generation: int) -> None:
    """Store a finished read (counted from its end) and forget it as in flight."""
    if _inflight.get(key) is task:
        _inflight.pop(key, None)
    if task.cancelled() or task.exception() is not None or generation != _generation:
        return
    now = time.monotonic()
    for k in [k for k, (expires, _) in _cache.items() if expires <= now]:
        del _cache[k]
    _cache[key] = (now + _CACHE_TTL_S, task.result())
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def _checked(given: Collection[str], allowed: frozenset[str], what: str) -> frozenset[str]:
    if isinstance(given, str):
        raise TypeError(f"{what} must be a collection of names, not a string")
    names = frozenset(given)
    unknown = names - allowed
    if unknown:
        raise ValueError(f"{what}: not read by crop-health: {sorted(unknown)}")
    return names


def pick(
    obs: Iterable[EOObservation],
    *,
    families: Collection[str],
    require: Collection[str],
    since: date | None = None,
) -> list[EOObservation]:
    """Observations of ``families`` that carry every ``require`` value, from ``since`` on, oldest first."""
    families = _checked(families, USED_FAMILIES, "families")
    require = _checked(require, USED_NAMES, "require")
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
