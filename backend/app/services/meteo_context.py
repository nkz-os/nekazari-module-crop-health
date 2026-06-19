"""Per-variable meteo source resolver — sensor > weather-map > regional.

The daily CropHealthAssessment is a daily snapshot. Sensor inputs MUST be
pre-windowed aggregates (e.g. from redis_state.get_window), never raw webhook
payloads. Seasonal GDD is handled separately by pipeline._fetch_gdd.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_VARIABLES = ("air_temp_c", "rh_pct", "et0_mm", "leaf_temp_c")
_FIDELITY_RANK = {"iot_sensor": 3, "parcel_weather": 2, "regional_proxy": 1, "unavailable": 0}


@dataclass
class MeteoContext:
    air_temp_c: float | None = None
    rh_pct: float | None = None
    et0_mm: float | None = None
    leaf_temp_c: float | None = None
    fidelity: dict[str, str] = field(default_factory=dict)
    dominant_fidelity: str = "unavailable"


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
    weather_map_fn=None,
    regional_fn=None,
) -> MeteoContext:
    sensor = sensor_ctx or {}
    wm = await _safe(weather_map_fn, parcel_id, tenant_id)
    regional = await _safe(regional_fn, parcel_id, tenant_id)

    ctx = MeteoContext()
    for var in _VARIABLES:
        if sensor.get(var) is not None:
            value, fidelity = sensor[var], "iot_sensor"
        elif wm.get(var) is not None:
            value, fidelity = wm[var], "parcel_weather"
        elif regional.get(var) is not None:
            value, fidelity = regional[var], "regional_proxy"
        else:
            value, fidelity = None, "unavailable"
        setattr(ctx, var, value)
        ctx.fidelity[var] = fidelity

    present = [f for f in ctx.fidelity.values() if f != "unavailable"]
    ctx.dominant_fidelity = (
        max(present, key=lambda f: _FIDELITY_RANK[f]) if present else "unavailable"
    )
    return ctx
