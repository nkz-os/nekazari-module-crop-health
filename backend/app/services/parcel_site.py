"""Where a parcel is and how it is watered, for the regional cereal calendar.

The stage table is regional for cereals, so its request carries the parcel
point and the irrigation regime. Both are optional: when the parcel cannot be
read the table is asked for without them, exactly as for any other crop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache

from nkz_platform_sdk.orion import OrionClient

from app.config import get_settings
from app.schemas import StageTable
from app.services import context_client

logger = logging.getLogger(__name__)

# Same reading as the planning module: a word we do not know is no regime, never a guess.
_IRRIGATED_WORDS = ("drip", "sprinkler", "flood", "pivot", "irrigat", "regad", "furrow", "gravity", "goteo",
                    "aspersi", "surco", "gravedad", "riego")
_RAINFED_WORDS = frozenset({"secano", "rainfed", "dryland", "none"})
_NEGATIONS = frozenset({"sin", "sense", "no", "non", "not", "without", "un"})
_NEGATING_PREFIXES = ("non", "un")

_TIMEOUT_S = 5.0
_site_cache: TTLCache[str, "ParcelSite"] = TTLCache(maxsize=512, ttl=3600)   # complete reads
_site_short: TTLCache[str, "ParcelSite"] = TTLCache(maxsize=512, ttl=60)     # partial or failed reads


@dataclass(frozen=True)
class ParcelSite:
    lat: float | None
    lon: float | None
    regime: str | None  # "rainfed" | "irrigated" | None


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value", value.get("@value"))
    return value


def regime_word(value: Any) -> str | None:
    text = str(_plain(value) or "").lower().replace("_", " ").replace("-", " ").strip()
    if not text:
        return None
    tokens = [t for t in re.split(r"\W+", text) if t]
    irrigated = any(w in text for w in _IRRIGATED_WORDS)
    if irrigated and any(
        tok in _NEGATIONS or any(tok.startswith(p) and tok[len(p):].startswith(_IRRIGATED_WORDS)
                                 for p in _NEGATING_PREFIXES)
        for tok in tokens
    ):
        return "rainfed"
    rainfed = bool(_RAINFED_WORDS & set(tokens))
    if irrigated == rainfed:
        return None
    return "irrigated" if irrigated else "rainfed"


def _point(loc: Any) -> tuple[float, float] | None:
    if isinstance(loc, dict) and loc.get("type") == "GeoProperty":
        loc = loc.get("value")
    if not isinstance(loc, dict):
        return None
    try:
        if loc.get("type") == "Point":
            lon, lat = loc["coordinates"][:2]
            return float(lat), float(lon)
        if loc.get("type") == "Polygon":
            ring = loc["coordinates"][0]
            return (sum(float(p[1]) for p in ring) / len(ring), sum(float(p[0]) for p in ring) / len(ring))
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
    return None


async def _read_site(client: Any, short: str, tenant_id: str) -> tuple[ParcelSite, bool]:
    """(site, complete). ``complete`` is False when a read FAILED; an absent crop is a complete answer."""
    complete = True
    pt = None
    parcel_regime = None
    try:
        entity = await client.get_entity(f"urn:ngsi-ld:AgriParcel:{short}", options="keyValues")
        entity = entity if isinstance(entity, dict) else {}
        pt = _point(entity.get("location"))
        for attr in ("irrigationSystemType", "irrigationRegime"):
            parcel_regime = regime_word(entity.get(attr))
            if parcel_regime:
                break
    except Exception as exc:  # noqa: BLE001
        complete = False
        logger.warning("parcel_site: parcel unreadable tenant=%s parcel=%s: %s", tenant_id, short, exc)
    crop_regime = None
    try:
        rows = await client.query_entities(
            type="AgriCrop",
            q=(f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{short}"'
               f'|refAgriParcel=="urn:ngsi-ld:AgriParcel:{short}"'),
            limit=10, options="keyValues")
        real = next((e for e in (rows or []) if isinstance(e, dict) and e.get("provenance") != "placeholder"), None)
        crop_regime = regime_word((real or {}).get("irrigationRegime"))
    except Exception as exc:  # noqa: BLE001
        complete = False
        logger.warning("parcel_site: crop unreadable tenant=%s parcel=%s: %s", tenant_id, short, exc)
    return ParcelSite(pt[0] if pt else None, pt[1] if pt else None, crop_regime or parcel_regime), complete


async def resolve_parcel_site(parcel_id: str, tenant_id: str) -> ParcelSite:
    """Point (centroid) and regime of a parcel; the crop's regime wins over the parcel's. Never raises.

    Both reads share one 5 s budget. A complete answer is cached for an hour; a partial or failed
    one for 60 s only, so an error never fixes a wrong regime and a broker outage costs one timeout a minute.
    """
    short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
    key = f"{tenant_id}:{short}"
    cached = _site_cache.get(key) or _site_short.get(key)
    if cached is not None:
        return cached
    client = None
    try:
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        site, complete = await asyncio.wait_for(_read_site(client, short, tenant_id), timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — incl. timeout and a failing constructor
        logger.warning("parcel_site: no site tenant=%s parcel=%s: %s", tenant_id, short, repr(exc))
        site, complete = ParcelSite(None, None, None), False
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
    (_site_cache if complete else _site_short)[key] = site
    return site


async def get_parcel_stage_table(species: str, parcel_id: str, tenant_id: str) -> StageTable:
    """Stage table for a parcel's crop.

    The plain species request comes first and is all that any other crop ever gets. Only a table
    that declares the cereal calendar model triggers the parcel read and the site-aware request;
    without a usable site the plain calendar table is kept (never the generic fallback).
    """
    base = await context_client.get_phenology_stages(species)
    # Anything that is not a calendar table (another crop, or a degraded/empty answer) is passed
    # through untouched: this path must never raise.
    if not isinstance(base, StageTable) or base.model is None:
        return base
    site = await resolve_parcel_site(parcel_id, tenant_id)
    kwargs: dict[str, Any] = {}
    if site.lat is not None and site.lon is not None:
        kwargs["lat"], kwargs["lon"] = site.lat, site.lon
    if site.regime is not None:
        kwargs["irrigation"] = site.regime
    if not kwargs:
        return base
    table = await context_client.get_phenology_stages(species, **kwargs)
    return table if isinstance(table, StageTable) and table.model is not None else base


async def parcel_regime(parcel_id: str, tenant_id: str) -> str | None:
    """``"rainfed"`` | ``"irrigated"`` of the parcel's crop (or of the parcel), None when not known.

    Never raises: an unreadable site is an unknown regime, which keeps the irrigated behaviour.
    """
    try:
        return (await resolve_parcel_site(parcel_id, tenant_id)).regime
    except Exception as exc:  # noqa: BLE001
        logger.warning("parcel_site: regime unreadable tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)
        return None


def gdd_kwargs(table: Any) -> dict[str, str]:
    """Extra ``_fetch_gdd`` keywords: the GDD method only when the table is the cereal calendar's."""
    if isinstance(table, StageTable) and table.gdd_method == "aquacrop_m3":
        return {"gdd_method": "aquacrop_m3"}
    return {}
