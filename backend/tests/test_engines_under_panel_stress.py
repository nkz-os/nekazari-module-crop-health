"""Under-panel water stress engine: pure functions."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.under_panel_stress import (
    WaterStress,
    compute_water_stress,
    ks_from_theta,
    par_open_from_ghi,
    shade_corrected_etc,
    volumetric_soil_moisture,
)
from app.schemas import SoilProperties
from app.services.redis_state import ParcelReading

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
SOIL = SoilProperties(
    field_capacity=0.27, wilting_point=0.12, has_data=True, hydraulics_from_soil=True
)
DEFAULT_SOIL = SoilProperties()


def reading(age_s: float, value: float = 15.0, unit: str | None = "P1", dev: str = "d-1"):
    return ParcelReading(dev, NOW.timestamp() - age_s, value, unit)


def run(readings, soil=SOIL, model_ks=None, model_fidelity="parcel_weather", shade=None):
    return compute_water_stress(readings, soil, 0.65, model_ks, model_fidelity, NOW, shade)


def test_volumetric_percent():
    assert volumetric_soil_moisture(23.5, "P1") == 0.235


def test_volumetric_rejects_unknown_unit_and_absurd_values():
    assert volumetric_soil_moisture(0.235, None) is None
    assert volumetric_soil_moisture(0.235, "C62") is None
    assert volumetric_soil_moisture(75.0, "P1") is None
    assert volumetric_soil_moisture(-1.0, "P1") is None
    assert volumetric_soil_moisture(float("nan"), "P1") is None


def test_ks_no_stress_above_raw():
    assert ks_from_theta(0.25, 0.27, 0.12, 0.65) == 1.0


def test_ks_linear_below_raw():
    assert ks_from_theta(0.15, 0.27, 0.12, 0.65) == pytest.approx(0.03 / 0.0525)


def test_ks_floor_zero():
    assert ks_from_theta(0.05, 0.27, 0.12, 0.65) == 0.0


def test_ks_rejects_fc_le_wp():
    with pytest.raises(ValueError):
        ks_from_theta(0.2, 0.1, 0.1, 0.5)


def test_par_open_none_at_night():
    assert par_open_from_ghi(20) is None
    assert par_open_from_ghi(float("nan")) is None


def test_par_open_conversion():
    assert par_open_from_ghi(500) == pytest.approx(1010.0)
    assert par_open_from_ghi(50) == pytest.approx(101.0)


def test_shade_corrected_etc():
    assert shade_corrected_etc(5.0, 1.0, None, 0.7) == 5.0
    assert shade_corrected_etc(5.0, 1.0, 0.5, 0.7) == pytest.approx(5.0 * (1 - 0.35))


def test_sensor_index_iot_with_soil_data():
    r = compute_water_stress([reading(600, 15.0), reading(120, 15.0)], SOIL, 0.65, None, "parcel_weather", NOW, 0.4)
    assert r.fidelity == "iot_sensor"
    assert r.index == round(1 - 0.03 / 0.0525, 3)
    assert r.observed_at == NOW - timedelta(seconds=600)
    assert r.shade_fraction == 0.4


def test_sensor_index_downgraded_with_default_soil():
    r = run([reading(60)], soil=DEFAULT_SOIL)
    assert r.fidelity == "regional_proxy"
    assert r.index is not None


def test_invalid_unit_falls_back_to_model():
    r = run([reading(60, unit=None)], model_ks=0.8)
    assert (r.index, r.fidelity, r.observed_at) == (0.2, "parcel_weather", NOW)


def test_old_and_future_readings_ignored():
    assert run([reading(3601)], model_ks=0.5).fidelity == "parcel_weather"
    assert run([reading(-301)], model_ks=0.5).fidelity == "parcel_weather"
    r = run([reading(-100)])
    assert r.fidelity == "iot_sensor"
    assert r.observed_at == NOW  # age never negative


def test_corrupt_soil_falls_back_to_model():
    bad = SoilProperties(field_capacity=0.1, wilting_point=0.1, has_data=True)
    r = run([reading(60)], soil=bad, model_ks=0.9)
    assert (r.index, r.fidelity) == (0.1, "parcel_weather")


@pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan"), float("inf")])
def test_bad_model_ks_is_none(bad):
    assert run([], model_ks=bad) == WaterStress(None, "unavailable", None, None)


def test_unavailable_without_sensor_or_model():
    r = run([], model_ks=None, shade=0.3)
    assert (r.index, r.fidelity, r.observed_at, r.shade_fraction) == (None, "unavailable", None, 0.3)


@pytest.mark.parametrize(
    "args",
    [
        (0.2, 0.27, 0.12, 1.0),
        (0.2, 0.27, 0.12, -0.1),
        (0.2, float("nan"), 0.12, 0.5),
        (0.2, 0.27, float("inf"), 0.5),
        (float("nan"), 0.27, 0.12, 0.5),
        (0.2, 0.27, 0.12, float("nan")),
    ],
)
def test_ks_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        ks_from_theta(*args)


def test_invalid_p_or_nan_soil_falls_back_to_model():
    r = compute_water_stress([reading(60)], SOIL, 1.0, 0.9, "parcel_weather", NOW, None)
    assert (r.index, r.fidelity) == (0.1, "parcel_weather")
    nan_soil = SoilProperties(field_capacity=float("nan"), wilting_point=0.12, has_data=True)
    r = run([reading(60)], soil=nan_soil, model_ks=0.9)
    assert (r.index, r.fidelity) == (0.1, "parcel_weather")
    assert run([reading(60)], soil=nan_soil).fidelity == "unavailable"


def test_mean_theta_of_two_readings():
    r = run([reading(60, 10.0), reading(60, 20.0, dev="d-2")])
    assert r.index == round(1 - ks_from_theta(0.15, 0.27, 0.12, 0.65), 3)


def test_invalid_older_reading_does_not_set_observed_at():
    r = run([reading(1800, 15.0, unit="C62"), reading(60, 15.0)])
    assert r.observed_at == NOW - timedelta(seconds=60)


def test_dead_probe_zero_is_rejected_and_uses_model(caplog):
    with caplog.at_level("WARNING"):
        r = run([reading(60, value=0.0, dev="dead-1")], model_ks=0.9)
    assert (r.index, r.fidelity) == (0.1, "parcel_weather")
    assert len([x for x in caplog.records if "dead-1" in x.getMessage()]) == 1


def test_fraction_mislabelled_as_percent_is_rejected():
    r = run([reading(60, value=0.25)], model_ks=0.9)
    assert (r.index, r.fidelity) == (0.1, "parcel_weather")


def test_dead_probe_dropped_before_mean():
    good = run([reading(60, value=15.0, dev="a")])
    mixed = run([reading(60, value=15.0, dev="a"), reading(60, value=0.0, dev="b")])
    assert mixed.fidelity == "iot_sensor"
    assert mixed.index == good.index


def test_volumetric_floor():
    assert volumetric_soil_moisture(1.9, "P1") is None
    assert volumetric_soil_moisture(2.0, "P1") == 0.02


def test_defaulted_hydraulics_are_proxy_even_with_has_data():
    soil = SoilProperties(field_capacity=0.27, wilting_point=0.12, has_data=True)
    r = run([reading(60)], soil=soil)
    assert r.fidelity == "regional_proxy"


def test_unavailable_model_fidelity_never_publishes_index():
    r = run([], model_ks=0.5, model_fidelity="unavailable", shade=0.2)
    assert (r.index, r.fidelity, r.observed_at, r.shade_fraction) == (None, "unavailable", None, 0.2)
