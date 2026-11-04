"""Per-variable meteo source resolver — sensor > zone > weather-map > regional.

The daily CropHealthAssessment is a daily snapshot. Sensor inputs MUST be
pre-windowed aggregates (e.g. from redis_state.get_window), never raw webhook
payloads. Seasonal GDD is handled separately by pipeline._fetch_gdd.

``instantaneous`` is separate from that precedence: the per-variable sources that may
pair with a leaf reading for the sensor CWSI (open-field parcel sensors, then a
WeatherObserved linked to the parcel), never a daily mean or an unlinked station.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from app.schemas import InstantValue

logger = logging.getLogger(__name__)

_VARIABLES = ("air_temp_c", "rh_pct", "et0_mm", "leaf_temp_c", "solar_radiation_wm2")
# Variables the sensor CWSI pairs with a leaf reading (spec §5.1, §14).
_INSTANT_VARIABLES = ("air_temp_c", "rh_pct", "solar_radiation_wm2")
_FIDELITY_RANK = {"iot_sensor": 4, "zone_weather": 3, "parcel_weather": 2, "regional_proxy": 1, "unavailable": 0}


@dataclass
class MeteoContext:
    air_temp_c: float | None = None
    rh_pct: float | None = None
    et0_mm: float | None = None
    leaf_temp_c: float | None = None
    solar_radiation_wm2: float | None = None
    air_temp_min_24h: float | None = None
    fidelity: dict[str, str] = field(default_factory=dict)
    # Epoch time of the observation behind each variable, when its source gives one
    # (``<var>_observed_ts`` or the source-wide ``observed_at_ts``).
    observed_at_ts: dict[str, float] = field(default_factory=dict)
    dominant_fidelity: str = "unavailable"
    # Per variable, the sources that may pair with a leaf reading, best first: the
    # parcel's own open-field sensors, then a WeatherObserved linked to the parcel.
    # Never the precedence-resolved value (weather-map/zone are daily means) and never
    # an unlinked tenant-wide observation.
    instantaneous: dict[str, list[InstantValue]] = field(default_factory=dict)


def _observed(source: dict, var: str) -> float | None:
    observed = source.get(f"{var}_observed_ts", source.get("observed_at_ts"))
    if isinstance(observed, (int, float)) and not isinstance(observed, bool):
        return float(observed)
    return None


def _instant_candidates(instant_sensor: dict, regional: dict) -> dict[str, list[InstantValue]]:
    out: dict[str, list[InstantValue]] = {}
    linked = regional.get("parcel_linked") is True
    for var in _INSTANT_VARIABLES:
        cands: list[InstantValue] = []
        for source, kind, ok in (
            (instant_sensor, "iot_sensor", True),
            (regional, "regional_proxy", linked),
        ):
            value = source.get(var)
            if not ok or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not math.isfinite(value):
                continue
            cands.append(InstantValue(value=float(value), source=kind, observed_ts=_observed(source, var)))
        if cands:
            out[var] = cands
    return out


async def _safe(fn, parcel_id, tenant_id) -> dict:
    if fn is None:
        return {}
    try:
        return await fn(parcel_id, tenant_id) or {}
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("meteo source failed for %s: %s", parcel_id, exc)
        return {}


async def resolve_meteo_context(
    parcel_id: str,
    tenant_id: str,
    *,
    sensor_ctx: dict | None = None,
    instant_sensor_ctx: dict | None = None,
    zone_ctx: dict | None = None,
    weather_map_fn=None,
    regional_fn=None,
) -> MeteoContext:
    sensor = sensor_ctx or {}
    zone = zone_ctx or {}
    wm = await _safe(weather_map_fn, parcel_id, tenant_id)
    regional = await _safe(regional_fn, parcel_id, tenant_id)

    ctx = MeteoContext()
    for var in _VARIABLES:
        source: dict = {}
        if sensor.get(var) is not None:
            source, fidelity = sensor, "iot_sensor"
        elif zone.get(var) is not None:
            source, fidelity = zone, "zone_weather"
        elif wm.get(var) is not None:
            source, fidelity = wm, "parcel_weather"
        elif regional.get(var) is not None:
            source, fidelity = regional, "regional_proxy"
        else:
            fidelity = "unavailable"
        setattr(ctx, var, source.get(var))
        ctx.fidelity[var] = fidelity
        observed = _observed(source, var)
        if observed is not None:
            ctx.observed_at_ts[var] = observed

    ctx.instantaneous = _instant_candidates(instant_sensor_ctx or {}, regional)

    ctx.air_temp_min_24h = zone.get("air_temp_min_24h")

    present = [f for f in ctx.fidelity.values() if f != "unavailable"]
    ctx.dominant_fidelity = (
        max(present, key=lambda f: _FIDELITY_RANK[f]) if present else "unavailable"
    )
    return ctx
