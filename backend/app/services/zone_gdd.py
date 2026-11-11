"""Per-zone GDD deviation from the parcel's area-weighted mean.

The parcel GDD stays authoritative (weather-api, gap-filled); each zone adds
only its own deviation from the weighted daily mean of the zones.
"""
from __future__ import annotations


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(x, hi))


def _daily_gdd(row: dict, base_temp: float, upper_cutoff: float, method: str = "legacy") -> float | None:
    """Daily GDD by the same method the parcel season GDD uses (weather-api).

    A day without both temperatures gives None (contributes nothing).
    """
    t_min, t_max = row.get("tMin"), row.get("tMax")
    if method not in _METHODS:
        raise ValueError(f"unknown GDD method: {method!r}")
    if t_min is None or t_max is None:
        return None
    lo, hi, b, u = float(t_min), float(t_max), base_temp, upper_cutoff
    if method == "m2":
        return (_clip(hi, b, u) + _clip(lo, b, u)) / 2.0 - b
    if method == "aquacrop_m3":
        return max((_clip(hi, b, u) + min(lo, u)) / 2.0, b) - b
    return max(0.0, (min(hi, u) + lo) / 2.0 - b)


_METHODS = ("legacy", "m2", "aquacrop_m3")


def zone_gdd_delta(
    daily_by_zone: dict[str, list[dict]],
    weights: dict[str, float],
    base_temp: float,
    upper_cutoff: float,
    gdd_method: str = "legacy",
) -> dict[str, float]:
    """Return, per zone id, sum over its days of (zone GDD - weighted day mean).

    The day mean uses only the zones present that day, weights renormalised.
    """
    per_zone: dict[str, dict[str, float]] = {}
    for zid, rows in daily_by_zone.items():
        days: dict[str, float] = {}
        for row in rows or []:
            day = row.get("date")
            g = _daily_gdd(row, base_temp, upper_cutoff, gdd_method)
            if day is None or g is None:
                continue
            days[day] = g
        per_zone[zid] = days

    all_days = {d for days in per_zone.values() for d in days}
    delta = {zid: 0.0 for zid in per_zone}
    for day in all_days:
        present = [z for z, days in per_zone.items() if day in days]
        total_w = sum(weights.get(z, 0.0) for z in present)
        if total_w > 0:
            mean = sum(weights.get(z, 0.0) * per_zone[z][day] for z in present) / total_w
        else:
            mean = sum(per_zone[z][day] for z in present) / len(present)
        for z in present:
            delta[z] += per_zone[z][day] - mean
    return delta
