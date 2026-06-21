"""Management-zone resolution for zonal crop-health synthesis.

crop-health CONSUMES zones from weather-map (``AgriParcelZone``); it never
generates them. When no zones exist the parcel itself is treated as a single
whole-parcel zone, preserving the legacy parcel-level behaviour exactly.

See: docs/superpowers/specs/2026-06-21-crop-health-zonal-synthesis-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)


@dataclass
class Zone:
    """A management zone of a parcel (or the whole parcel as fallback)."""
    zone_id: str
    geometry: dict
    urn: str | None = None
    sensor_nearby: bool = False
    centroid: tuple[float, float] | None = None


def _orion(tenant_id: str) -> OrionClient:
    s = get_settings()
    return OrionClient(tenant_id, base_url=s.orion_ld_url, context_url=s.orion_ld_context)


def is_whole_parcel(zones: list[Zone]) -> bool:
    return len(zones) == 1 and zones[0].zone_id == "parcel"


def _attr(row: dict, *names: str):
    """First present value among candidate keys (handles nkz: prefix vs compacted)."""
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return None


def _zone_id_from(row: dict) -> str | None:
    zid = _attr(row, "nkz:zoneId", "zoneId")
    if zid:
        return str(zid)
    # Fallback: AgriParcelZone URN is ...:{tenant}:{parcel}:{zoneId}
    urn = row.get("id", "")
    if urn:
        return urn.split(":")[-1] or None
    return None


def _centroid_from(row: dict) -> tuple[float, float] | None:
    c = _attr(row, "nkz:centroid", "centroid")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        return (float(c[0]), float(c[1]))
    return None


async def resolve_zones(parcel_id: str, tenant_id: str, parcel_geometry: dict) -> list[Zone]:
    """Return the parcel's ``AgriParcelZone`` zones, or a whole-parcel fallback.

    Empty / error → exactly one whole-parcel zone (``zone_id="parcel"``) so the
    caller's behaviour is identical to today when weather-map has not zoned the
    parcel. Result is sorted by ``zone_id`` for deterministic iteration.
    """
    urn = parcel_id if parcel_id.startswith("urn:") else f"urn:ngsi-ld:AgriParcel:{parcel_id}"
    client = _orion(tenant_id)
    try:
        rows = await client.query_entities(
            type="AgriParcelZone",
            q=f'(hasAgriParcel=="{urn}"|refAgriParcel=="{urn}")',
            options="keyValues",
            limit=100,
        ) or []
    except Exception as exc:  # fail-safe: no zones → whole-parcel mode
        logger.warning("resolve_zones: query failed for %s — whole-parcel fallback: %s", urn, exc)
        rows = []
    finally:
        await client.close()

    zones: list[Zone] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        zid = _zone_id_from(r)
        if not zid:
            continue
        geom = _attr(r, "location") or parcel_geometry
        # keyValues GeoProperty → geometry dict directly; normalized → {value: geom}
        if isinstance(geom, dict) and geom.get("type") == "GeoProperty":
            geom = geom.get("value") or parcel_geometry
        sensor_nearby = bool(_attr(r, "nkz:sensorNearby", "sensorNearby") or False)
        zones.append(Zone(
            zone_id=zid,
            geometry=geom,
            urn=r.get("id") or None,
            sensor_nearby=sensor_nearby,
            centroid=_centroid_from(r),
        ))

    if not zones:
        return [Zone(zone_id="parcel", geometry=parcel_geometry)]
    return sorted(zones, key=lambda z: z.zone_id)
