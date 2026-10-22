"""
Unit tests for biophysical engines.

Verifies VPD, CWSI, MDS, and water balance calculations
against known-good reference values.
"""

import math

import pytest

from app.engines.mds_model import calculate_mds_from_readings, mds_severity
from app.engines.water_balance import dynamic_water_balance
from app.engines.water_stress import (
    cwsi,
    cwsi_with_weather,
    saturation_vapor_pressure,
    vapor_pressure_deficit,
)
from app.schemas import Severity, TimeseriesPoint


# ═══════════════════════════════════════════════════════════════════════════════
# VPD / CWSI Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSaturationVaporPressure:
    """Tetens formula (FAO-56) validation."""

    def test_at_20c(self):
        # FAO-56 table: es(20°C) ≈ 2.338 kPa
        result = saturation_vapor_pressure(20.0)
        assert abs(result - 2.338) < 0.01

    def test_at_25c(self):
        # FAO-56 table: es(25°C) ≈ 3.167 kPa
        result = saturation_vapor_pressure(25.0)
        assert abs(result - 3.167) < 0.01

    def test_at_0c(self):
        # es(0°C) ≈ 0.6108 kPa
        result = saturation_vapor_pressure(0.0)
        assert abs(result - 0.6108) < 0.01

    def test_at_35c(self):
        # es(35°C) ≈ 5.623 kPa
        result = saturation_vapor_pressure(35.0)
        assert abs(result - 5.623) < 0.01


class TestVPD:
    """Vapor Pressure Deficit tests."""

    def test_vpd_25c_60rh(self):
        # es(25°C) ≈ 3.167, ea = 3.167 * 0.6 = 1.900, VPD ≈ 1.267
        result = vapor_pressure_deficit(25.0, 60.0)
        assert abs(result - 1.267) < 0.02

    def test_vpd_100rh_is_zero(self):
        result = vapor_pressure_deficit(25.0, 100.0)
        assert result == 0.0

    def test_vpd_0rh_equals_es(self):
        result = vapor_pressure_deficit(25.0, 0.0)
        es = saturation_vapor_pressure(25.0)
        assert abs(result - es) < 0.001

    def test_vpd_invalid_humidity_raises(self):
        with pytest.raises(ValueError):
            vapor_pressure_deficit(25.0, 101.0)
        with pytest.raises(ValueError):
            vapor_pressure_deficit(25.0, -1.0)


class TestCWSI:
    """Crop Water Stress Index tests."""

    def test_midpoint(self):
        # Tc=35, Ta=30 → diff=5, D1=2, D2=8 → (5-2)/(8-2) = 0.5
        result = cwsi(35.0, 30.0, 2.0, 8.0)
        assert result.cwsi == 0.5

    def test_no_stress(self):
        # Tc=31, Ta=30 → diff=1, D1=2, D2=8 → (1-2)/(8-2) = -1/6 → clamped to 0
        result = cwsi(31.0, 30.0, 2.0, 8.0)
        assert result.cwsi == 0.0

    def test_max_stress(self):
        # Tc=40, Ta=30 → diff=10, D1=2, D2=8 → (10-2)/(8-2) = 1.33 → clamped to 1
        result = cwsi(40.0, 30.0, 2.0, 8.0)
        assert result.cwsi == 1.0

    def test_canopy_cooler_than_air(self):
        # Well-irrigated: Tc < Ta → should be 0
        result = cwsi(28.0, 30.0, 2.0, 8.0)
        assert result.cwsi == 0.0

    def test_d1_equals_d2_raises(self):
        with pytest.raises(ValueError):
            cwsi(35.0, 30.0, 5.0, 5.0)

    def test_with_weather_includes_vpd(self):
        result = cwsi_with_weather(35.0, 30.0, 60.0, 2.0, 8.0)
        assert result.cwsi == 0.5
        assert result.vpd_kpa > 0  # VPD should be computed


# ═══════════════════════════════════════════════════════════════════════════════
# MDS Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestMDSSeverity:
    """Severity classification from MDS ratio."""

    def test_low(self):
        assert mds_severity(120.0, 150.0) == Severity.LOW    # ratio 0.8

    def test_medium(self):
        assert mds_severity(195.0, 150.0) == Severity.MEDIUM  # ratio 1.3

    def test_high(self):
        assert mds_severity(240.0, 150.0) == Severity.HIGH    # ratio 1.6

    def test_critical(self):
        assert mds_severity(315.0, 150.0) == Severity.CRITICAL  # ratio 2.1

    def test_zero_ref_returns_medium(self):
        # Safety: zero ref → can't compute ratio → MEDIUM as precaution
        assert mds_severity(100.0, 0.0) == Severity.MEDIUM


class TestMDSCalculation:
    """MDS from trunk diameter readings."""

    def test_normal_shrinkage(self):
        readings = [
            TimeseriesPoint(ts=1000.0, value=5000.0),  # µm
            TimeseriesPoint(ts=2000.0, value=5100.0),
            TimeseriesPoint(ts=3000.0, value=4900.0),
            TimeseriesPoint(ts=4000.0, value=5050.0),
        ]
        result = calculate_mds_from_readings(readings, mds_ref=150.0)
        assert result is not None
        # max=5100, min=4900, MDS=200µm, ratio=200/150=1.33
        assert result.mds_um == 200.0
        assert result.severity == Severity.MEDIUM

    def test_insufficient_data(self):
        readings = [TimeseriesPoint(ts=1000.0, value=5000.0)]
        result = calculate_mds_from_readings(readings, mds_ref=150.0)
        assert result is None

    def test_empty_readings(self):
        result = calculate_mds_from_readings([], mds_ref=150.0)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Water Balance Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestWaterBalance:
    """Dynamic water balance calculations."""

    def test_surplus(self):
        result = dynamic_water_balance(10.0, 5.0, 0.85)
        # ETc = 5.0 * 0.85 = 4.25, Balance = 10 - 4.25 = 5.75
        assert result.balance_mm == 5.75
        assert not result.deficit

    def test_deficit(self):
        result = dynamic_water_balance(2.0, 8.0, 0.85)
        # ETc = 8.0 * 0.85 = 6.8, Balance = 2 - 6.8 = -4.8
        assert result.balance_mm == -4.8
        assert result.deficit

    def test_soil_moisture_correction(self):
        # Without correction
        result_no_soil = dynamic_water_balance(2.0, 8.0, 0.85)
        # With dry soil (5% → amplify deficit)
        result_dry = dynamic_water_balance(2.0, 8.0, 0.85, soil_moisture_pct=5.0)
        # Dry soil should amplify deficit
        assert result_dry.balance_mm < result_no_soil.balance_mm

    def test_soil_correction_not_applied_on_surplus(self):
        # Even with dry soil, no correction if balance > 0
        result = dynamic_water_balance(10.0, 5.0, 0.85, soil_moisture_pct=5.0)
        assert result.balance_mm > 0  # Still positive

    def test_zero_precipitation(self):
        result = dynamic_water_balance(0.0, 6.0, 1.0)
        assert result.balance_mm == -6.0
        assert result.deficit
