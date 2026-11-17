"""Cross weather-map terrain-unit weather onto current-zoning zones.

A zone's weather is the mean of the terrain units that overlap it, weighted by
overlap. Overlap is sampled on a metric grid (deterministic, hole-aware); units
that cover too little of the zone give no zone weather (the parcel's is used).
"""
from __future__ import annotations

import math
from datetime import datetime

from nkz_platform_sdk.gis.zones import point_in_polygon

from app.services.zonation import Zone

_M_PER_DEG_LAT = 111320.0
_MAX_SAMPLES = 400_000


def _bbox(geometry: dict) -> tuple[float, float, float, float] | None:
    kind = (geometry or {}).get("type")
    coords = (geometry or {}).get("coordinates") or []
    polys = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
    pts = [p for poly in polys for ring in poly for p in ring]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def overlap_fractions(
    zone_geometry: dict, units: list[Zone], step_m: float = 10.0
) -> tuple[dict[str, float], float, dict[str, float]]:
    """(share per unit normalised over the covered part, covered fraction, overlap ha per unit)."""
    box = _bbox(zone_geometry)
    if box is None or not units:
        return {}, 0.0, {}
    x0, y0, x1, y1 = box
    mid_lat = (y0 + y1) / 2.0
    dy = step_m / _M_PER_DEG_LAT
    dx = step_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 1e-6))
    nx = max(1, round((x1 - x0) / dx))
    ny = max(1, round((y1 - y0) / dy))
    while nx * ny > _MAX_SAMPLES:  # very large zone: coarsen, keep determinism
        dx, dy = dx * 2, dy * 2
        step_m *= 2
        nx = max(1, round((x1 - x0) / dx))
        ny = max(1, round((y1 - y0) / dy))
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny  # grid spans the bbox exactly
    ordered = sorted(units, key=lambda u: u.zone_id)
    counts: dict[str, int] = {}
    inside = 0
    for i in range(nx):
        lon = x0 + (i + 0.5) * dx
        for j in range(ny):
            lat = y0 + (j + 0.5) * dy
            if not point_in_polygon(lon, lat, zone_geometry):
                continue
            inside += 1
            for u in ordered:
                if point_in_polygon(lon, lat, u.geometry):
                    counts[u.zone_id] = counts.get(u.zone_id, 0) + 1
                    break
    hit = sum(counts.values())
    if inside == 0 or hit == 0:
        return {}, 0.0, {}
    cell_ha = (step_m * step_m) / 10_000.0
    fractions = {k: v / hit for k, v in counts.items()}
    return fractions, hit / inside, {k: v * cell_ha for k, v in counts.items()}


def _wmean(pairs: list[tuple[float, float]]) -> float | None:
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    return sum(v * w for v, w in pairs) / total


def apply_terrain_meteo(
    zone: Zone,
    units: list[Zone],
    fractions: dict[str, float],
    covered: float,
    overlap_ha: dict[str, float],
    *,
    min_covered: float = 0.5,
    min_share: float = 0.10,
    min_ha: float = 0.1,
) -> None:
    """Fill the zone's weather from the weighted terrain units; no-op if coverage is low."""
    if covered < min_covered:
        return
    used = [(u, fractions.get(u.zone_id, 0.0)) for u in units if fractions.get(u.zone_id, 0.0) > 0]
    if not used:
        return
    for attr in ("t_min", "t_max", "eto", "solar_radiation_wm2"):
        val = _wmean([(getattr(u, attr), w) for u, w in used if getattr(u, attr) is not None])
        if val is not None:
            setattr(zone, attr, val)
    with_tmin = [(u, w) for u, w in used if u.t_min is not None]
    if with_tmin:
        sig = [u for u, w in with_tmin if w >= min_share or overlap_ha.get(u.zone_id, 0.0) >= min_ha]
        if not sig:
            sig = [max(with_tmin, key=lambda p: p[1])[0]]
        zone.t_min_coldest = min(u.t_min for u in sig)
    stamps: list[datetime] = [u.observed_at for u, _ in used if u.observed_at is not None]
    if stamps:
        zone.observed_at = min(stamps)


def cross_daily(daily_by_unit: dict[str, list[dict]], fractions: dict[str, float]) -> list[dict]:
    """Per-date weighted ``{date, tMin, tMax, eto}``, renormalised over units with data that day."""
    by_date: dict[str, list[tuple[dict, float]]] = {}
    for uid, rows in daily_by_unit.items():
        w = fractions.get(uid, 0.0)
        if w <= 0:
            continue
        for r in rows:
            if r.get("date"):
                by_date.setdefault(r["date"], []).append((r, w))
    out = []
    for date in sorted(by_date):
        row = {"date": date}
        for key in ("tMin", "tMax", "eto"):
            row[key] = _wmean([(r[key], w) for r, w in by_date[date] if r.get(key) is not None])
        out.append(row)
    return out
