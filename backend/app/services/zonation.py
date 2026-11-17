"""Management-zone resolution for zonal crop-health synthesis.

crop-health evaluates per level of the parcel's current zoning
(``AgriManagementZone``, one zone per level); it never generates zones. The
weather-map terrain units (``AgriParcelZone``) are only an input for weather
(``fetch_terrain_units``). With no usable current zoning the parcel itself is
a single whole-parcel zone, the legacy parcel-level behaviour.

See: docs/superpowers/specs/2026-06-21-crop-health-zonal-synthesis-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from nkz_platform_sdk.gis.zones import default_zoning, group_zonings
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
    zone_type: str | None = None
    zone_version: str | None = None
    zone_rank: int | None = None
    area_ha: float | None = None
    pixel_count: int | None = None
    t_min: float | None = None
    t_max: float | None = None
    eto: float | None = None
    solar_radiation_wm2: float | None = None
    frost_risk: float | None = None
    observed_at: datetime | None = None
    sensor_distance_m: float | None = None
    zone_level: str | None = None
    t_min_coldest: float | None = None


def _orion(tenant_id: str) -> OrionClient:
    s = get_settings()
    return OrionClient(tenant_id, base_url=s.orion_ld_url, context_url=s.orion_ld_context)


def is_whole_parcel(zones: list[Zone]) -> bool:
    return len(zones) == 1 and zones[0].zone_id == "parcel"


NKZ_NS = "https://nkz-os.org/ns/"


def _attr(row: dict, *names: str):
    """First present value among candidate keys.

    A producer term that is not in the platform @context reaches us under its
    full IRI (``https://nkz-os.org/ns/centroid``), so every bare name is also
    tried with that namespace, besides the ``nkz:`` prefix and compacted forms.
    """
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
        bare = n.split(":", 1)[1] if n.startswith("nkz:") else n
        for key in (NKZ_NS + bare, "nkz:" + bare):
            if key in row and row[key] is not None:
                return row[key]
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


def _num(value, cast=float):
    """Numeric value (plain or ``{"value": ...}``-wrapped) or None."""
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _observed_at_from(row: dict) -> datetime | None:
    """``dateObserved`` as an aware datetime; ISO string or ``{"@value": ...}``."""
    raw = _attr(row, "dateObserved")
    if isinstance(raw, dict):
        raw = raw.get("@value", raw.get("value"))
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def zone_weights(zones: list[Zone]) -> dict[str, float]:
    """Normalised weight per zone_id: area, else pixel count, else equal."""
    if not zones:
        return {}
    if all(z.area_ha is not None for z in zones):
        raw = [float(z.area_ha) for z in zones]
    elif all(z.pixel_count is not None for z in zones):
        raw = [z.pixel_count * 0.01 for z in zones]
    else:
        raw = [1.0] * len(zones)
    total = sum(raw)
    if total <= 0:
        raw, total = [1.0] * len(zones), float(len(zones))
    return {z.zone_id: w / total for z, w in zip(zones, raw)}


MAX_MANAGEMENT_PARTS = 5


def _geometry_of(row: dict) -> dict | None:
    """Row geometry as a GeoJSON dict (keyValues or GeoProperty-wrapped)."""
    geom = _attr(row, "location")
    if isinstance(geom, dict) and geom.get("type") == "GeoProperty":
        geom = geom.get("value")
    return geom if isinstance(geom, dict) else None


def _has_management_geometry(row: dict) -> bool:
    geom = _geometry_of(row)
    if not geom:
        return False
    gtype = geom.get("type")
    if gtype == "Polygon":
        return True
    if gtype == "MultiPolygon":
        return 1 <= len(geom.get("coordinates") or []) <= MAX_MANAGEMENT_PARTS
    return False


def _is_management_by_heuristic(row: dict) -> bool:
    """Weather-map zones: centroid/aspect sector and no TWI statistic."""
    if _attr(row, "nkz:twiMean", "twiMean") is not None:
        return False
    return (
        _attr(row, "nkz:centroid", "centroid") is not None
        or _attr(row, "nkz:aspectSector", "aspectSector") is not None
    )


def is_management_zone(row: dict) -> bool:
    """True if ``row`` is a management zone (not a TWI class or geometry-less zone).

    A row that declares ``zoneType`` is a management zone only if it says so; a
    row without one goes through the weather-map heuristic. Decided per row.
    """
    if not _has_management_geometry(row):
        return False
    zone_type = _attr(row, "nkz:zoneType", "zoneType")
    if zone_type is not None:
        return zone_type in ("management", "terrain")
    return _is_management_by_heuristic(row)


def select_management_zones(rows: list[dict]) -> list[dict]:
    """Management zones among a parcel's rows, each judged on its own."""
    return [r for r in rows if isinstance(r, dict) and is_management_zone(r)]


def _parcel_urn(parcel_id: str) -> str:
    return parcel_id if parcel_id.startswith("urn:") else f"urn:ngsi-ld:AgriParcel:{parcel_id}"


async def fetch_terrain_units(parcel_id: str, tenant_id: str) -> list[Zone]:
    """Weather-map terrain units (``AgriParcelZone``) of a parcel, by ``zone_id``.

    Management/terrain units only (TWI and hydrology classes are excluded).
    They carry the per-unit weather; no whole-parcel fallback (empty on error).
    """
    urn = _parcel_urn(parcel_id)
    client = _orion(tenant_id)
    try:
        rows = await client.query_entities(
            type="AgriParcelZone",
            q=f'(hasAgriParcel=="{urn}"|refAgriParcel=="{urn}")',
            options="keyValues",
            limit=100,
        ) or []
    except Exception as exc:  # fail-safe: no zones → whole-parcel mode
        logger.warning("fetch_terrain_units: query failed for %s — no terrain units: %s", urn, exc)
        rows = []
    finally:
        await client.close()

    zones: list[Zone] = []
    for r in select_management_zones(rows):
        zid = _zone_id_from(r)
        if not zid:
            continue
        geom = _geometry_of(r) or {}
        sensor_nearby = bool(_attr(r, "nkz:sensorNearby", "sensorNearby") or False)
        zones.append(Zone(
            zone_id=zid,
            geometry=geom,
            urn=r.get("id") or None,
            sensor_nearby=sensor_nearby,
            centroid=_centroid_from(r),
            zone_type=_attr(r, "nkz:zoneType", "zoneType"),
            zone_version=_attr(r, "nkz:zoneVersion", "zoneVersion"),
            zone_rank=_num(_attr(r, "nkz:zoneRank", "zoneRank"), int),
            area_ha=_num(_attr(r, "nkz:areaHa", "areaHa")),
            pixel_count=_num(_attr(r, "nkz:pixelCount", "pixelCount"), int),
            t_min=_num(_attr(r, "tMin")),
            t_max=_num(_attr(r, "tMax")),
            eto=_num(_attr(r, "eto")),
            solar_radiation_wm2=_num(_attr(r, "nkz:solarRadiationWm2", "solarRadiationWm2")),
            frost_risk=_num(_attr(r, "nkz:frostRisk", "frostRisk")),
            observed_at=_observed_at_from(r),
            sensor_distance_m=_num(_attr(r, "nkz:sensorDistanceM", "sensorDistanceM")),
        ))

    return sorted(zones, key=lambda z: z.zone_id)




_LEVELS = ("high", "medium", "low", "critical")
_CURRENT_METHOD = "vegetationIndexMultiDate"
_ZONING_PAGE = 100
_ZONING_MAX_PAGES = 10


def _whole_parcel(parcel_geometry: dict) -> list[Zone]:
    return [Zone(zone_id="parcel", geometry=parcel_geometry)]


async def resolve_zones(parcel_id: str, tenant_id: str, parcel_geometry: dict) -> list[Zone]:
    """One ``Zone`` per level of the parcel's current multidate zoning.

    The current zoning is the most recent automatic one. It is used only if
    its method is ``vegetationIndexMultiDate`` and every zone carries a
    distinct, known ``zoneLevel``; anything else (no zoning, other method,
    manual, missing/duplicated level, Orion error) is the whole parcel.
    ``zone_id`` is the level code, sorted by ``zone_rank``. Current-zoning
    zones may have many parts and holes: no part limit applies to them.
    """
    urn = _parcel_urn(parcel_id)
    client = _orion(tenant_id)
    rows: list[dict] = []
    try:
        for page in range(_ZONING_MAX_PAGES):
            batch = await client.query_entities(
                type="AgriManagementZone",
                q=f'hasAgriParcel=="{urn}"',
                options="keyValues",
                limit=_ZONING_PAGE,
                offset=page * _ZONING_PAGE,
            ) or []
            rows.extend(r for r in batch if isinstance(r, dict))
            if len(batch) < _ZONING_PAGE:
                break
    except Exception as exc:  # fail-safe: whole-parcel mode
        logger.warning("resolve_zones: query failed for %s — whole-parcel fallback: %s", urn, exc)
        return _whole_parcel(parcel_geometry)
    finally:
        await client.close()

    current = default_zoning(group_zonings(rows))
    if current is None or current.method != _CURRENT_METHOD:
        return _whole_parcel(parcel_geometry)

    by_id = {r.get("id"): r for r in rows}
    zones: list[Zone] = []
    seen: set[str] = set()
    for ref in current.zones:
        row = by_id.get(ref.id) or {}
        level = _attr(row, "zoneLevel")
        if level not in _LEVELS or level in seen or not ref.geometry:
            logger.warning("resolve_zones: unusable current zoning for %s (level=%r) — whole parcel", urn, level)
            return _whole_parcel(parcel_geometry)
        seen.add(level)
        zones.append(Zone(
            zone_id=level,
            geometry=ref.geometry,
            urn=ref.id or None,
            zone_type="management",
            zone_version=_attr(row, "zoningRunId") or current.run_id,
            zone_rank=_num(_attr(row, "zoneRank"), int),
            area_ha=_num(_attr(row, "areaHa")),
            zone_level=level,
        ))
    if not zones:
        return _whole_parcel(parcel_geometry)
    return sorted(zones, key=lambda z: (z.zone_rank is None, z.zone_rank or 0, z.zone_id))


def point_in_polygon(lon: float, lat: float, geometry: dict) -> bool:
    """Ray-casting point-in-polygon for a GeoJSON Polygon/MultiPolygon (outer ring)."""
    def _ring(ring) -> bool:
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and (
                lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
            ):
                inside = not inside
            j = i
        return inside

    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return _ring(coords[0]) if coords else False
    if gtype == "MultiPolygon":
        return any(poly and _ring(poly[0]) for poly in coords)
    return False


def sensors_in_zone(zone: Zone, sensors: list[dict]) -> list[dict]:
    """Sensors whose (lon, lat) fall inside the zone polygon.

    Sensors without coordinates cannot be spatially assigned and are skipped
    (in the whole-parcel fallback the polygon is the parcel, so every located
    sensor of the parcel falls in — capturing the multi-sensor case there too).
    """
    out = []
    for s in sensors:
        lon, lat = s.get("lon"), s.get("lat")
        if lon is None or lat is None:
            continue
        if point_in_polygon(float(lon), float(lat), zone.geometry):
            out.append(s)
    return out


_NON_METRIC = {"id", "lon", "lat", "dateObserved"}


def consolidate_sensor_readings(sensors: list[dict]) -> dict:
    """Mean per numeric metric across a zone's sensors.

    This is the intrazone last-write-wins fix: when ≥2 sensors share a zone the
    assessment represents the zone's consolidated state, not the last reading.
    """
    if not sensors:
        return {}
    acc: dict[str, list[float]] = {}
    for s in sensors:
        for k, v in s.items():
            if k in _NON_METRIC:
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                acc.setdefault(k, []).append(float(v))
    return {k: sum(vs) / len(vs) for k, vs in acc.items() if vs}
