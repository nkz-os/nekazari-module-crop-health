from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.meteo_context import resolve_meteo_context
from app.services.zonation import Zone
from app.services.zone_inputs import gather_zone_inputs, zone_meteo_ctx

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
_SQ = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}


def _zone(zid="z1", age_h=2, **kw):
    base = dict(t_min=10.0, t_max=21.0, eto=4.0, solar_radiation_wm2=250.0,
                observed_at=NOW - timedelta(hours=age_h))
    base.update(kw)
    return Zone(zone_id=zid, geometry=_SQ, **base)


def test_zone_meteo_ctx_fresh():
    assert zone_meteo_ctx(_zone(), NOW) == {
        "air_temp_c": 15.5, "air_temp_min_24h": 10.0, "et0_mm": 4.0,
        "solar_radiation_wm2": 250.0,
    }


def test_zone_meteo_ctx_drops_none_and_needs_both_temps():
    ctx = zone_meteo_ctx(_zone(t_max=None, eto=None), NOW)
    assert "air_temp_c" not in ctx and "et0_mm" not in ctx
    assert ctx["air_temp_min_24h"] == 10.0


def test_zone_meteo_ctx_stale_or_unobserved():
    assert zone_meteo_ctx(_zone(age_h=48), NOW) == {}
    assert zone_meteo_ctx(_zone(observed_at=None), NOW) == {}


@pytest.mark.asyncio
async def test_stale_zone_falls_back_to_parcel_weather():
    async def wm(p, t):
        return {"air_temp_c": 22.0}
    ctx = await resolve_meteo_context(
        "p", "t", zone_ctx=zone_meteo_ctx(_zone(age_h=48), NOW), weather_map_fn=wm,
    )
    assert ctx.fidelity["air_temp_c"] == "parcel_weather"


async def _no_sensors(p, t):
    return []


@pytest.mark.asyncio
async def test_gather_zone_inputs_with_daily():
    calls = []

    async def fetch(parcel, tenant, start, end):
        calls.append((start, end))
        return {"z1": [{"date": "2026-07-09", "tMin": 9, "tMax": 20, "eto": 3.5}]}

    out = await gather_zone_inputs(
        "urn:ngsi-ld:AgriParcel:p1", "p1", "acme", [_zone("z1"), _zone("z2", age_h=60)],
        date(2026, 4, 1), NOW, fetch_daily=fetch, gather_sensors=_no_sensors,
    )
    assert calls == [(date(2026, 4, 1), date(2026, 7, 10))]
    assert out["z1"].weather_daily[0]["tMin"] == 9
    assert out["z1"].fidelity["meteo"] == "zone_specific"
    assert out["z1"].fidelity["gdd"] == "zone_specific"
    assert out["z2"].weather_daily == []
    assert out["z2"].fidelity["meteo"] == "parcel_inherited"
    assert out["z2"].fidelity["gdd"] == "parcel_inherited"
    assert out["z1"].ndvi is None and out["z1"].fidelity["ndvi"] == "parcel_inherited"


@pytest.mark.asyncio
async def test_gather_zone_inputs_empty_and_no_season_start():
    calls = []

    async def fetch(parcel, tenant, start, end):
        calls.append(start)
        return {}

    z = _zone("z1", observed_at=None)
    out = await gather_zone_inputs(
        "p1", "p1", "acme", [z], None, NOW, fetch_daily=fetch, gather_sensors=_no_sensors,
    )
    assert calls == [date(2026, 7, 10) - timedelta(days=120)]
    assert out["z1"].fidelity["meteo"] == "parcel_inherited"
    assert out["z1"].fidelity["gdd"] == "parcel_inherited"


def test_zone_meteo_ctx_naive_datetimes_treated_as_utc():
    naive_obs = _zone(observed_at=datetime(2026, 7, 10, 10, 0))
    assert zone_meteo_ctx(naive_obs, NOW)["air_temp_c"] == 15.5
    assert zone_meteo_ctx(_zone(age_h=2), NOW.replace(tzinfo=None))["air_temp_c"] == 15.5
    assert zone_meteo_ctx(_zone(observed_at=datetime(2026, 7, 8, 10, 0)), NOW) == {}
