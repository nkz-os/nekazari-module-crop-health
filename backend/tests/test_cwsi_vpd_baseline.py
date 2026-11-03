"""CWSI from published VPD-dependent baselines (no invented numbers, no silent defaults)."""
from __future__ import annotations

import logging
import types
from datetime import datetime, timezone

import pytest

from app.engines.water_stress import (
    CWSI_MIN_VPD_KPA,
    cwsi_from_baseline,
    nwsb_c,
    select_baseline,
    upper_limit_c,
    vapor_pressure_deficit,
)
from app.schemas import CwsiBaseline, MetricType, WaterStressReference
from app.services import pipeline
from app.services.parcel_link import OPEN_FIELD
from app.services.redis_state import ParcelReading
from tests.test_pipeline_under_panel_stress import NOW, _setup
from tests.test_under_panel_sensor_gating import DEVICE, SOIL, GateRedis, _owner, _run


def _b(id="b", *, a0=3.38, a1=-3.25, upper=None, valid=None, stages=None, cultivar=None, ref="Synthetic 2000"):
    return CwsiBaseline.model_validate({
        "id": id, "cultivar": cultivar, "stages": stages,
        "a0C": a0, "a1CPerKpa": a1,
        "upper": upper or {"form": "constant", "valueC": 1.0},
        "valid": valid or {"solarHourFrom": 10, "solarHourTo": 16, "vpdKpaMin": 1.0, "clearSky": True},
        "ref": ref,
    })


def test_nwsb_idso_wheat():
    assert nwsb_c(_b(), 2.0) == pytest.approx(-3.12)


def test_linear_vpd_upper():
    b = _b(upper={"form": "linear_vpd", "a0C": 6.451, "a1CPerKpa": 0.635})
    assert upper_limit_c(b, 30.0, 3.0) == pytest.approx(8.356)


def test_idso1981_upper_not_computed():
    b = _b(upper={"form": "idso1981"})
    assert upper_limit_c(b, 30.0, 3.0) is None
    assert cwsi_from_baseline(30.0, 30.0, 20.0, b, 12.0) is None


def test_cwsi_clamped_0_1():
    b = _b()  # at Ta 35 / RH 20 VPD is high; NWSB very negative, UL 1.0
    cold = cwsi_from_baseline(20.0, 35.0, 20.0, b, 12.0)
    hot = cwsi_from_baseline(45.0, 35.0, 20.0, b, 12.0)
    assert cold.cwsi == 0.0
    assert hot.cwsi == 1.0
    assert hot.baseline_id == "b" and hot.method_ref == "Synthetic 2000"
    assert hot.nwsb_c < hot.upper_c == 1.0


def test_cwsi_midpoint():
    b = _b()
    vpd = vapor_pressure_deficit(35.0, 20.0)
    nwsb = nwsb_c(b, vpd)
    tc = 35.0 + (nwsb + 1.0) / 2
    assert cwsi_from_baseline(tc, 35.0, 20.0, b, 12.0).cwsi == pytest.approx(0.5, abs=1e-3)


def test_outside_solar_window_none():
    assert cwsi_from_baseline(40.0, 35.0, 20.0, _b(), 8.0) is None
    assert cwsi_from_baseline(40.0, 35.0, 20.0, _b(), 17.0) is None


def test_vpd_below_min_none():
    assert vapor_pressure_deficit(25.0, 60.0) < CWSI_MIN_VPD_KPA
    assert cwsi_from_baseline(28.0, 25.0, 60.0, _b(), 12.0) is None
    # a baseline's own higher minimum wins
    b = _b(valid={"vpdKpaMin": 4.0, "clearSky": True})
    assert cwsi_from_baseline(40.0, 35.0, 40.0, b, 12.0) is None


def test_upper_not_above_nwsb_none():
    assert cwsi_from_baseline(40.0, 35.0, 20.0, _b(upper={"form": "constant", "valueC": -50.0}), 12.0) is None


def test_select_baseline_prefers_cultivar_then_stage():
    generic = _b("generic")
    staged = _b("staged", stages=["flowering"])
    cult = _b("cult", stages=["flowering"], cultivar="Alpha")
    other_cult = _b("other", cultivar="Beta")
    ref = WaterStressReference(baselines=[generic, staged, other_cult, cult])
    assert select_baseline(ref, "flowering", "Alpha").id == "cult"
    assert select_baseline(ref, "flowering", None).id == "staged"
    assert select_baseline(ref, "vegetative", None).id == "generic"
    assert select_baseline(ref, "flowering", "Gamma").id == "staged"
    assert select_baseline(WaterStressReference(baselines=[staged]), "vegetative", None) is None
    assert select_baseline(None, "flowering", None) is None


# ── pipeline ────────────────────────────────────────────────────────────────

def _params_with(monkeypatch, ref):
    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=-2.0, d2=2.0,
            species="OLVEU", water_stress_reference=ref)

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)


def _coords(monkeypatch, lon=0.0):
    async def _c(*a, **k):
        return (40.0, lon)

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _c, raising=False)


def _hot_ref():
    return WaterStressReference(baselines=[_b(valid={"solarHourFrom": 10, "solarHourTo": 16, "clearSky": True})])


async def _trigger(monkeypatch, ref, *, lon=0.0, wm=None, ts_offsets=(60,)):
    published, _ = _setup(monkeypatch, soil=SOIL, wm=wm or {"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, ref)
    _coords(monkeypatch, lon)
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - o, 38.0, "CEL") for o in ts_offsets]})
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    return published["assessments"][-1]


@pytest.mark.asyncio
async def test_pipeline_cwsi_from_baseline(monkeypatch):
    a = await _trigger(monkeypatch, _hot_ref())
    assert a.cwsi is not None
    assert a.cwsi.baseline_id == "b" and a.cwsi.temp_source == "leaf_temperature"


@pytest.mark.asyncio
async def test_no_baseline_no_cwsi(monkeypatch):
    assert (await _trigger(monkeypatch, None)).cwsi is None
    assert (await _trigger(monkeypatch, WaterStressReference(baselines=[]))).cwsi is None


@pytest.mark.asyncio
async def test_no_longitude_no_cwsi(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, _hot_ref())

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _none, raising=False)
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 38.0, "CEL")]})
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    assert published["assessments"][-1].cwsi is None


@pytest.mark.asyncio
async def test_all_readings_outside_solar_window_no_cwsi(monkeypatch):
    # NOW is 12:00 UTC; longitude 150 E -> solar hour 22, outside 10-16
    assert (await _trigger(monkeypatch, _hot_ref(), lon=150.0)).cwsi is None


@pytest.mark.asyncio
async def test_vpd_below_min_pipeline_no_cwsi(monkeypatch):
    a = await _trigger(monkeypatch, _hot_ref(), wm={"air_temp_c": 22.0, "rh_pct": 70.0, "et0_mm": 5.0})
    assert a.cwsi is None


@pytest.mark.asyncio
async def test_median_of_window_used(monkeypatch):
    seen = {}
    real = pipeline.cwsi_from_baseline

    def spy(tc, *a, **k):
        seen["tc"] = tc
        return real(tc, *a, **k)

    monkeypatch.setattr(pipeline, "cwsi_from_baseline", spy)
    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, _hot_ref())
    _coords(monkeypatch)
    _owner(monkeypatch, OPEN_FIELD)
    pts = [ParcelReading(DEVICE, NOW - 60 * i, v, "CEL") for i, v in enumerate([30.0, 38.0, 45.0], 1)]
    await _run(MetricType.LEAF_TEMPERATURE, GateRedis(window={"leafTemperature": pts}))
    assert seen["tc"] == 38.0


@pytest.mark.asyncio
async def test_satellite_path_disabled_logs_reason(monkeypatch, caplog):
    called = []

    async def _lst(*a, **k):
        called.append(1)
        return 30.0, "2026-07-15"

    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, _hot_ref())
    monkeypatch.setattr(pipeline, "_fetch_parcel_lst_with_date", _lst, raising=False)
    _owner(monkeypatch, OPEN_FIELD)
    with caplog.at_level(logging.INFO):
        await _run(MetricType.SOIL_MOISTURE, GateRedis())
    assert published["assessments"][-1].cwsi is None
    assert called == []
    assert any(
        "CWSI satellite skipped: phase 2 (per-pixel hourly meteo and Landsat scene time)" in r.getMessage()
        for r in caplog.records
    )


# ── fix round 1 ─────────────────────────────────────────────────────────────

def _w(id, lo, hi, **kw):
    return _b(id, valid={"solarHourFrom": lo, "solarHourTo": hi, "clearSky": True}, **kw)


def test_window_is_half_open_adjacent_rows():
    ref = WaterStressReference(baselines=[_w("h11", 11, 12), _w("h12", 12, 13)])
    assert select_baseline(ref, None, None, 12.0).id == "h12"
    assert select_baseline(ref, None, None, 11.99).id == "h11"
    assert select_baseline(ref, None, None, 13.0) is None
    assert cwsi_from_baseline(40.0, 35.0, 20.0, ref.baselines[0], 12.0) is None
    assert cwsi_from_baseline(40.0, 35.0, 20.0, ref.baselines[1], 12.0) is not None


def test_select_by_solar_hour_among_null_stage_rows():
    ref = WaterStressReference(baselines=[_w("h10", 10, 11), _w("h11", 11, 12), _w("h12", 12, 13)])
    assert select_baseline(ref, None, None, 12.5).id == "h12"
    assert select_baseline(ref, "flowering", None, 10.2).id == "h10"
    # no hour: file order
    assert select_baseline(ref, None, None).id == "h10"


def test_tier_without_valid_hour_falls_through():
    staged = _w("staged", 10, 11, stages=["flowering"])
    generic = _w("generic", 11, 14)
    ref = WaterStressReference(baselines=[staged, generic])
    assert select_baseline(ref, "flowering", None, 12.0).id == "generic"
    assert select_baseline(ref, "flowering", None, 10.5).id == "staged"


def test_cultivar_match_case_insensitive():
    ref = WaterStressReference(baselines=[_b("g"), _b("c", cultivar="Alpha")])
    assert select_baseline(ref, None, "  alpha ").id == "c"


def test_non_finite_inputs_none():
    nan = float("nan")
    assert cwsi_from_baseline(nan, 35.0, 20.0, _b(), 12.0) is None
    assert cwsi_from_baseline(40.0, nan, 20.0, _b(), 12.0) is None
    assert cwsi_from_baseline(40.0, 35.0, nan, _b(), 12.0) is None


@pytest.mark.asyncio
async def test_pipeline_stage_specific_row_not_chosen_without_gdd(monkeypatch):
    staged_only = WaterStressReference(baselines=[_w("s", 10, 16, stages=["vegetative"])])
    assert (await _trigger(monkeypatch, staged_only)).cwsi is None


@pytest.mark.asyncio
async def test_pipeline_noon_selects_noon_row(monkeypatch):
    ref = WaterStressReference(baselines=[_w("h10", 10, 11), _w("h11", 11, 12), _w("h12", 12, 13)])
    a = await _trigger(monkeypatch, ref, lon=7.5)  # NOW = 12:00 UTC -> solar hour 12.5
    assert a.cwsi is not None and a.cwsi.baseline_id == "h12"


@pytest.mark.asyncio
async def test_nan_reading_does_not_give_cwsi_one(monkeypatch):
    seen = {}
    real = pipeline.cwsi_from_baseline

    def spy(tc, *a, **k):
        seen["tc"] = tc
        return real(tc, *a, **k)

    monkeypatch.setattr(pipeline, "cwsi_from_baseline", spy)
    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, _hot_ref())
    _coords(monkeypatch)
    _owner(monkeypatch, OPEN_FIELD)
    vals = [float("nan"), 38.0, 500.0, 36.0, float("inf")]
    pts = [ParcelReading(DEVICE, NOW - 60 * i, v, "CEL") for i, v in enumerate(vals, 1)]
    await _run(MetricType.LEAF_TEMPERATURE, GateRedis(window={"leafTemperature": pts}))
    assert seen["tc"] == 37.0  # median of 38 and 36 only


@pytest.mark.asyncio
async def test_all_invalid_readings_no_cwsi(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0})
    _params_with(monkeypatch, _hot_ref())
    _coords(monkeypatch)
    _owner(monkeypatch, OPEN_FIELD)
    pts = [ParcelReading(DEVICE, NOW - 60 * i, v, "CEL") for i, v in enumerate([float("nan"), 999.0], 1)]
    await _run(MetricType.LEAF_TEMPERATURE, GateRedis(window={"leafTemperature": pts}))
    assert published["assessments"][-1].cwsi is None
