"""Sensor CWSI needs instantaneous air (I1) and, where the baseline says so, a clear sky (I2)."""
from __future__ import annotations

import logging
import types
from datetime import datetime, timezone

import pytest

from app.engines.water_stress import (
    CLEAR_SKY_MIN_RS_RSO,
    clear_sky_radiation_wm2,
    extraterrestrial_radiation_wm2,
    select_baseline,
    sky_clear,
)
from app.schemas import CwsiBaseline, MetricType, WaterStressReference
from app.services import pipeline
from app.services.meteo_context import resolve_meteo_context
from app.services.parcel_link import OPEN_FIELD
from app.services.redis_state import ParcelReading
from tests.test_pipeline_under_panel_stress import NOW, _setup
from tests.test_post_maturity import _no_network, _offline_context  # noqa: F401  (autouse: offline)
from tests.test_under_panel_sensor_gating import DEVICE, SOIL, GateRedis, _owner, _run

# ── FAO-56 radiation (chapter 3) ─────────────────────────────────────────────

# FAO-56 Example 19: N'Diaye (Senegal) 16°13'N 16°15'W, 8 m, 1 October (J = 274),
# 14:00-15:00 local clock with Lz = 15° W (= 15:00-16:00 UTC): Ra = 3.543 MJ m-2 h-1,
# Rso = 2.658 MJ m-2 h-1.
_EX19_TS = datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc).timestamp()
_EX19_LAT = 16 + 13 / 60
_EX19_LON = -16.25
_MJ_H_TO_WM2 = 1e6 / 3600


def test_hourly_ra_matches_fao56_example_19():
    ra = extraterrestrial_radiation_wm2(_EX19_LAT, _EX19_LON, _EX19_TS)
    assert ra == pytest.approx(3.543 * _MJ_H_TO_WM2, rel=2e-3)
    assert clear_sky_radiation_wm2(ra, 8.0) == pytest.approx(2.658 * _MJ_H_TO_WM2, rel=2e-3)


def test_ra_zero_at_night():
    night = datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc).timestamp()
    assert extraterrestrial_radiation_wm2(_EX19_LAT, _EX19_LON, night) == 0.0


def test_sky_clear_ratio():
    rso = clear_sky_radiation_wm2(extraterrestrial_radiation_wm2(_EX19_LAT, _EX19_LON, _EX19_TS), 0.0)
    assert sky_clear(rso * 0.9, _EX19_LAT, _EX19_LON, _EX19_TS) is True
    assert sky_clear(rso * (CLEAR_SKY_MIN_RS_RSO - 0.01), _EX19_LAT, _EX19_LON, _EX19_TS) is False
    assert sky_clear(None, _EX19_LAT, _EX19_LON, _EX19_TS) is None
    assert sky_clear(float("nan"), _EX19_LAT, _EX19_LON, _EX19_TS) is None
    night = datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc).timestamp()
    assert sky_clear(10.0, _EX19_LAT, _EX19_LON, night) is None


# ── baseline selection minors ────────────────────────────────────────────────

def _b(id, **kw):
    return CwsiBaseline.model_validate({
        "id": id, "a0C": 1.0, "a1CPerKpa": -1.0, "upper": {"form": "constant", "valueC": 5.0},
        "valid": {"clearSky": True}, **kw,
    })


def test_cultivar_name_separators_are_one_space():
    ref = WaterStressReference(baselines=[_b("pn", cultivar="Pinot Noir")])
    assert select_baseline(ref, None, "Pinot-noir").id == "pn"
    assert select_baseline(ref, None, "pinot_noir").id == "pn"
    assert select_baseline(ref, None, " PINOT  -  NOIR ").id == "pn"


def test_stage_specific_cultivar_row_wins_over_all_stage_cultivar_row():
    ref = WaterStressReference(baselines=[
        _b("cv-all", cultivar="Alpha"), _b("cv-flower", cultivar="Alpha", stages=["flowering"]),
    ])
    assert select_baseline(ref, "flowering", "Alpha").id == "cv-flower"
    assert select_baseline(ref, "vegetative", "Alpha").id == "cv-all"


# ── meteo context carries observation times ──────────────────────────────────

@pytest.mark.asyncio
async def test_meteo_context_keeps_observation_time_per_variable():
    async def _reg(*a, **k):
        return {"air_temp_c": 30.0, "rh_pct": 20.0, "observed_at_ts": 123.0}

    async def _wm(*a, **k):
        return {"air_temp_c": 31.0}

    ctx = await resolve_meteo_context(
        "p", "t", sensor_ctx={"solar_radiation_wm2": 800.0, "solar_radiation_wm2_observed_ts": 99.0},
        weather_map_fn=_wm, regional_fn=_reg,
    )
    assert ctx.fidelity["air_temp_c"] == "parcel_weather" and "air_temp_c" not in ctx.observed_at_ts
    assert ctx.observed_at_ts["rh_pct"] == 123.0
    assert ctx.observed_at_ts["solar_radiation_wm2"] == 99.0


# ── pipeline ────────────────────────────────────────────────────────────────

def _ref(clear_sky=False):
    return WaterStressReference(baselines=[CwsiBaseline.model_validate({
        "id": "b", "a0C": 3.38, "a1CPerKpa": -3.25,
        "upper": {"form": "constant", "valueC": 1.0},
        "valid": {"solarHourFrom": 10, "solarHourTo": 16, "clearSky": clear_sky},
    })])


async def _cwsi_run(monkeypatch, *, wm=None, regional=None, by_context=None, leaf=38.0, ref=None, lat=40.0):
    published, _ = _setup(monkeypatch, soil=SOIL, wm=wm or {}, regional=regional or {})

    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=None, d2=None,
            species="OLVEU", water_stress_reference=ref or _ref())

    async def _coords(*a, **k):
        return (lat, 0.0)

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(
        by_context=by_context or {},
        window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, leaf, "CEL")]},
    )
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    return published["assessments"][-1]


# A WeatherObserved linked to the parcel (hasAgriParcel/refAgriParcel), as _regional_meteo marks it.
_AIR = {"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0, "parcel_linked": True}


@pytest.mark.asyncio
async def test_weather_map_daily_mean_air_never_gives_cwsi(monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        a = await _cwsi_run(
            monkeypatch, wm={"air_temp_c": 35.0, "et0_mm": 5.0},
            regional={"rh_pct": 20.0, "observed_at_ts": NOW - 600, "parcel_linked": True},
        )
    assert a.cwsi is None
    assert a.water_stress_indicator.method != "cwsi_sensor"
    assert any("CWSI skipped: air not instantaneous" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_hourly_observation_within_one_hour_gives_cwsi(monkeypatch):
    a = await _cwsi_run(monkeypatch, regional={**_AIR, "observed_at_ts": NOW - 1800})
    assert a.cwsi is not None


@pytest.mark.asyncio
async def test_observation_older_than_one_hour_no_cwsi(monkeypatch):
    a = await _cwsi_run(monkeypatch, regional={**_AIR, "observed_at_ts": NOW - 2 * 3600})
    assert a.cwsi is None


@pytest.mark.asyncio
async def test_observation_without_time_no_cwsi(monkeypatch):
    a = await _cwsi_run(monkeypatch, regional=dict(_AIR))
    assert a.cwsi is None


@pytest.mark.asyncio
async def test_parcel_air_sensors_give_cwsi(monkeypatch):
    by_context = {
        (OPEN_FIELD, "airTemperature"): [ParcelReading("air", NOW - 120, 35.0, "CEL")],
        (OPEN_FIELD, "relativeHumidity"): [ParcelReading("air", NOW - 120, 20.0, "P1")],
    }
    a = await _cwsi_run(monkeypatch, by_context=by_context)
    assert a.cwsi is not None


def _rso_at_now(lat=40.0):
    return clear_sky_radiation_wm2(extraterrestrial_radiation_wm2(lat, 0.0, NOW), 0.0)


@pytest.mark.asyncio
async def test_clear_sky_baseline_overcast_reading_no_cwsi(monkeypatch, caplog):
    regional = {**_AIR, "solar_radiation_wm2": _rso_at_now() * 0.4, "observed_at_ts": NOW - 600}
    with caplog.at_level(logging.INFO):
        a = await _cwsi_run(monkeypatch, regional=regional, ref=_ref(clear_sky=True))
    assert a.cwsi is None
    assert any("CWSI skipped: sky not clear" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_clear_sky_baseline_clear_reading_gives_cwsi(monkeypatch):
    regional = {**_AIR, "solar_radiation_wm2": _rso_at_now() * 0.95, "observed_at_ts": NOW - 600}
    a = await _cwsi_run(monkeypatch, regional=regional, ref=_ref(clear_sky=True))
    assert a.cwsi is not None


@pytest.mark.asyncio
async def test_parcel_pyranometer_decides_the_sky(monkeypatch):
    by_context = {(OPEN_FIELD, "solarRadiation"): [ParcelReading("pyr", NOW - 120, _rso_at_now() * 0.3, "D54")]}
    regional = {**_AIR, "observed_at_ts": NOW - 600}
    a = await _cwsi_run(monkeypatch, regional=regional, by_context=by_context, ref=_ref(clear_sky=True))
    assert a.cwsi is None


@pytest.mark.asyncio
async def test_unknown_sky_low_cwsi_falls_back_to_balance(monkeypatch, caplog):
    # Leaf far below air: CWSI 0 with no radiation -> could be overcast, never "none".
    with caplog.at_level(logging.INFO):
        a = await _cwsi_run(monkeypatch, regional={**_AIR, "observed_at_ts": NOW - 600}, leaf=20.0,
                            ref=_ref(clear_sky=True))
    assert a.cwsi is None
    assert a.water_stress_indicator.level != "none" or a.water_stress_indicator.method == "balance"
    assert any("sky unknown" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_unknown_sky_high_cwsi_is_kept(monkeypatch):
    a = await _cwsi_run(monkeypatch, regional={**_AIR, "observed_at_ts": NOW - 600}, leaf=38.0,
                        ref=_ref(clear_sky=True))
    assert a.cwsi is not None and a.cwsi.cwsi >= 0.2
