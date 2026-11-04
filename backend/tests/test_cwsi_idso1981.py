"""Idso et al. 1981 (Agric. Meteorol. 24:45-55) upper limit and daylight window."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.engines.water_stress import (
    cwsi_from_baseline,
    daylight_window_solar_hours,
    in_solar_window,
    saturation_vapor_pressure as es,
    select_baseline,
    upper_limit_c,
)
from app.schemas import CwsiBaseline, WaterStressReference


def _row(**over):
    d = {
        "id": "idso-test", "a0C": 2.00, "a1CPerKpa": -1.87,
        "upper": {"form": "idso1981"},
        "valid": {"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": True},
    }
    d.update(over)
    return CwsiBaseline.model_validate(d)


def _ts(month, day, hour_utc=12):
    return datetime(2026, month, day, hour_utc, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("ta,mb", [(10, 1.7), (20, 3.0), (30, 5.1), (40, 8.2), (50, 12.8)])
def test_vpg_matches_idso_p52(ta, mb):
    vpg = es(ta + 2.0) - es(ta)
    assert vpg == pytest.approx(mb / 10, abs=0.01)


def test_squash_upper_limit_at_30c():
    # a1 -0.187 C/mb = -1.87 C/kPa
    assert upper_limit_c(_row(), 30.0, 3.0) == pytest.approx(3.0, abs=0.1)


def test_paper_example_cwsi():
    # VPD 4.0 kPa, Tf - Ta = -1 C, Ta 30 C
    from app.engines import water_stress as ws
    rh = 100 * (1 - 4.0 / es(30.0))
    b = _row(valid={"clearSky": False})
    r = cwsi_from_baseline(29.0, 30.0, rh, b, 12.0)
    assert r is not None
    assert ws.vapor_pressure_deficit(30.0, rh) == pytest.approx(4.0, abs=1e-6)
    assert r.cwsi == pytest.approx(0.53, abs=0.02)


def test_daylight_window_shrinks_in_winter():
    jun = daylight_window_solar_hours(40.0, _ts(6, 21), 3, 3)
    dec = daylight_window_solar_hours(40.0, _ts(12, 21), 3, 3)
    assert jun[0] < dec[0] < 12 < dec[1] < jun[1]
    assert (jun[1] - jun[0]) == pytest.approx(15.0 - 6, abs=0.3)  # ~15 h day
    assert (dec[1] - dec[0]) == pytest.approx(9.0 - 6, abs=0.3)  # ~9 h day


def test_reading_outside_daylight_window_gives_no_cwsi():
    b = _row(valid={"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": False})
    ts = _ts(12, 21)
    rh = 20.0
    assert cwsi_from_baseline(30.0, 35.0, rh, b, 12.0, lat_deg=40.0, ts_unix=ts) is not None
    assert cwsi_from_baseline(30.0, 35.0, rh, b, 9.0, lat_deg=40.0, ts_unix=ts) is None
    assert cwsi_from_baseline(30.0, 35.0, rh, b, 15.5, lat_deg=40.0, ts_unix=ts) is None


def test_missing_latitude_gives_no_cwsi():
    b = _row(valid={"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": False})
    assert not in_solar_window(b, 12.0, None, _ts(6, 21))
    assert cwsi_from_baseline(30.0, 35.0, 20.0, b, 12.0, ts_unix=_ts(6, 21)) is None
    assert daylight_window_solar_hours(float("nan"), _ts(6, 21), 3, 3) is None


def test_hours_cannot_mix_with_explicit_solar_hours():
    with pytest.raises(ValidationError):
        _row(valid={"solarHourFrom": 11, "solarHourTo": 13, "hoursAfterSunrise": 3,
                    "hoursBeforeSunset": 3, "clearSky": False})
    with pytest.raises(ValidationError):
        _row(valid={"solarHourFrom": 11, "hoursAfterSunrise": 3, "hoursBeforeSunset": 3,
                    "clearSky": False})


@pytest.mark.parametrize("only", ["hoursAfterSunrise", "hoursBeforeSunset"])
def test_hours_must_come_in_pairs(only):
    with pytest.raises(ValidationError):
        _row(valid={only: 3, "clearSky": False})


def test_collapsed_window_is_none():
    # 12 h day at the equinox, 7 h + 7 h trimmed -> lo >= hi
    assert daylight_window_solar_hours(0.0, _ts(3, 21), 7, 7) is None


def test_60n_december_window_collapses_no_cwsi():
    # ~5.5 h of daylight: 3 h after sunrise + 3 h before sunset leaves nothing.
    assert daylight_window_solar_hours(60.0, _ts(12, 21), 3, 3) is None
    b = _row(valid={"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": False})
    assert cwsi_from_baseline(30.0, 35.0, 20.0, b, 12.0, lat_deg=60.0, ts_unix=_ts(12, 21)) is None


@pytest.mark.parametrize("month", [6, 12])
def test_70n_polar_day_and_night_no_window_no_crash(month):
    assert daylight_window_solar_hours(70.0, _ts(month, 21), 3, 3) is None
    b = _row(valid={"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": False})
    assert not in_solar_window(b, 12.0, 70.0, _ts(month, 21))
    assert cwsi_from_baseline(30.0, 35.0, 20.0, b, 12.0, lat_deg=70.0, ts_unix=_ts(month, 21)) is None


def test_missing_latitude_logs_a_distinct_line_without_tenant(caplog):
    import logging
    b = _row(valid={"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": False})
    with caplog.at_level(logging.INFO):
        assert not in_solar_window(b, 12.0, None, _ts(6, 21))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("daylight window cannot be evaluated: latitude or time missing" in m for m in msgs)
    assert not any("tenant" in m for m in msgs)


def test_bioorch_payload_parses_and_selects():
    ref = WaterStressReference.model_validate({"baselines": [{
        "id": "x", "a0C": 2.0, "a1CPerKpa": -1.87, "stages": None,
        "upper": {"form": "idso1981"},
        "valid": {"hoursAfterSunrise": 3, "hoursBeforeSunset": 3, "clearSky": True},
    }]})
    b = select_baseline(ref, None, None, 12.0, 40.0, _ts(6, 21))
    assert b is not None and b.valid.hours_after_sunrise == 3
    assert select_baseline(ref, None, None, 12.0, None, _ts(6, 21)) is None
