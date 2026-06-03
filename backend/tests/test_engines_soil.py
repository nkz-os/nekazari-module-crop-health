"""Tests for soil-aware water balance and waterlogging risk engines."""
import pytest
from app.engines.soil_water_balance import soil_water_balance
from app.engines.waterlogging_risk import waterlogging_risk


# ── Soil Water Balance tests ──────────────────────────────────────────────

def test_soil_water_balance_no_stress():
    """Full soil, precip matches ETc — no stress."""
    result = soil_water_balance(
        sw_yesterday=50.0,
        precip_mm=5.0,
        irrigation_mm=0.0,
        etc_mm=5.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.sw_ratio > 0.5
    assert result.stress_level == "none"
    assert result.excess_mm == 0.0


def test_soil_water_balance_moderate_stress():
    """Soil depleting below 50% AWC triggers moderate stress."""
    awc = (0.30 - 0.12) * 500  # 90 mm
    result = soil_water_balance(
        sw_yesterday=awc * 0.6,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=10.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.sw_ratio < 0.5
    assert result.sw_ratio > 0.3
    assert result.stress_level == "moderate"


def test_soil_water_balance_critical_stress():
    """Soil below 15% AWC triggers critical stress."""
    awc = (0.30 - 0.12) * 500
    result = soil_water_balance(
        sw_yesterday=awc * 0.2,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=15.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.sw_ratio < 0.15
    assert result.stress_level == "critical"


def test_soil_water_balance_excess():
    """Water exceeding AWC produces excess for waterlogging."""
    awc = (0.30 - 0.12) * 500
    result = soil_water_balance(
        sw_yesterday=awc * 0.9,
        precip_mm=50.0,
        irrigation_mm=0.0,
        etc_mm=5.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.excess_mm > 0
    assert result.sw_mm == pytest.approx(awc, rel=0.01)


def test_soil_water_balance_irrigation_counted():
    """Irrigation is added to inflow."""
    result = soil_water_balance(
        sw_yesterday=50.0,
        precip_mm=0.0,
        irrigation_mm=20.0,
        etc_mm=5.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.inflow_mm == 20.0
    assert result.sw_mm > 50.0


def test_soil_water_balance_cold_start():
    """None SW triggers cold start (returns 50% AWC)."""
    awc = (0.30 - 0.12) * 500
    result = soil_water_balance(
        sw_yesterday=None,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=5.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.soil_moisture_confidence == "low"
    assert result.sw_mm == pytest.approx(awc * 0.5 - 5.0, rel=0.01)
    assert result.stress_level == "moderate"  # 44%, below 50% threshold


def test_soil_water_balance_sw_never_negative():
    """Soil water cannot go below 0."""
    result = soil_water_balance(
        sw_yesterday=1.0,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=20.0,
        fc=0.30,
        wp=0.12,
        root_depth_mm=500,
    )
    assert result.sw_mm == 0.0
    assert result.sw_ratio == 0.0
    assert result.stress_level == "critical"


def test_soil_water_balance_sandy_soil_low_awc():
    """Sandy soil (FC-WP small) has low AWC, stress faster."""
    result = soil_water_balance(
        sw_yesterday=10.0,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=8.0,
        fc=0.12,   # sand FC
        wp=0.04,   # sand WP
        root_depth_mm=500,
    )
    awc = (0.12 - 0.04) * 500  # 40 mm
    assert awc == pytest.approx(40.0)
    assert result.stress_level == "critical"  # SW drops from 10 to 2, ratio 0.05


# ── Waterlogging Risk tests ──────────────────────────────────────────────

def test_waterlogging_no_risk_when_no_excess():
    """Zero excess means no waterlogging risk."""
    result = waterlogging_risk(excess_mm=0.0, ksat_mm_h=13.0, scs_group="B")
    assert result.risk_level == "LOW"
    assert result.saturation_hours == 0.0


def test_waterlogging_fast_drainage_reduces_risk():
    """Group A soils drain fast, reducing saturation hours."""
    result = waterlogging_risk(excess_mm=50.0, ksat_mm_h=50.0, scs_group="A")
    assert result.saturation_hours < 5
    assert result.risk_level == "LOW"


def test_waterlogging_slow_drainage_increases_risk():
    """Group D soils barely drain, high risk with modest excess."""
    result = waterlogging_risk(excess_mm=20.0, ksat_mm_h=0.3, scs_group="D")
    assert result.saturation_hours > 48
    assert result.risk_level == "CRITICAL"


def test_waterlogging_medium_risk():
    """Moderate excess with moderate drainage."""
    result = waterlogging_risk(excess_mm=30.0, ksat_mm_h=3.0, scs_group="C")
    assert result.risk_level in ("MEDIUM", "HIGH")
    assert result.saturation_hours > 0
