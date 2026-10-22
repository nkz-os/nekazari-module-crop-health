import pytest
from app.services.meteo_context import resolve_meteo_context, MeteoContext


async def _wm(parcel, tenant):  # weather-map baseline
    return {"air_temp_c": 22.0, "rh_pct": 55.0, "et0_mm": 4.1}

async def _regional(parcel, tenant):
    return {"air_temp_c": 20.0, "rh_pct": 60.0}


@pytest.mark.asyncio
async def test_sensor_overrides_weather_map_per_variable():
    ctx = await resolve_meteo_context(
        "p1", "t1",
        sensor_ctx={"air_temp_c": 28.0},   # windowed aggregate, not raw payload
        weather_map_fn=_wm, regional_fn=_regional,
    )
    assert ctx.air_temp_c == 28.0
    assert ctx.fidelity["air_temp_c"] == "iot_sensor"
    assert ctx.rh_pct == 55.0                       # from weather-map
    assert ctx.fidelity["rh_pct"] == "parcel_weather"

@pytest.mark.asyncio
async def test_regional_fallback_when_weather_map_missing_variable():
    async def _wm_partial(parcel, tenant): return {"air_temp_c": 22.0}
    ctx = await resolve_meteo_context(
        "p1", "t1", sensor_ctx=None, weather_map_fn=_wm_partial, regional_fn=_regional,
    )
    assert ctx.rh_pct == 60.0
    assert ctx.fidelity["rh_pct"] == "regional_proxy"

@pytest.mark.asyncio
async def test_unavailable_when_no_source():
    async def _empty(parcel, tenant): return {}
    ctx = await resolve_meteo_context("p1", "t1", weather_map_fn=_empty, regional_fn=_empty)
    assert ctx.air_temp_c is None
    assert ctx.fidelity["air_temp_c"] == "unavailable"
    assert ctx.dominant_fidelity == "unavailable"

@pytest.mark.asyncio
async def test_dominant_fidelity_picks_best_present():
    ctx = await resolve_meteo_context(
        "p1", "t1", sensor_ctx={"air_temp_c": 28.0}, weather_map_fn=_wm, regional_fn=_regional,
    )
    assert ctx.dominant_fidelity == "iot_sensor"
