"""Tests for compaction_risk engine."""

import pytest
from app.engines.compaction_risk import evaluate_compaction_risk


# ── Baseline: low susceptibility alone ──

def test_low_susceptibility_alone_is_low_risk():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=20,
        soil_susceptibility_class="low",
    )
    assert result.risk_level == "low"
    assert result.risk_score < 30
    assert result.requires_field_verification is False


def test_high_susceptibility_alone_is_moderate_risk():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=65,
        soil_susceptibility_class="high",
    )
    # Base: 65 * 0.50 = 32.5 → moderate (30-50)
    assert result.risk_level == "moderate"
    assert not result.moisture_warning


def test_very_high_susceptibility_alone():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=85,
        soil_susceptibility_class="very_high",
    )
    # Base: 85 * 0.50 = 42.5 → moderate
    assert result.risk_level == "moderate"
    assert result.requires_field_verification is False  # no vigor concern yet


# ── Moisture warning ──

def test_wet_soil_on_high_susceptibility_triggers_warning():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=70,
        soil_susceptibility_class="high",
        soil_moisture_pct=30.0,
    )
    assert result.moisture_warning is True
    assert "wet_soil_on_susceptible_ground" in result.contributing_factors
    assert result.advisory == "compaction.advisory.avoid_traffic_wet_soil"


def test_wet_soil_on_low_susceptibility_no_warning():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=20,
        soil_susceptibility_class="low",
        soil_moisture_pct=30.0,
    )
    # moisture is high but soil is low susceptibility → just factor, no warning
    assert result.moisture_warning is False
    assert "wet_soil" in result.contributing_factors


def test_dry_soil_no_moisture_warning():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=70,
        soil_susceptibility_class="high",
        soil_moisture_pct=15.0,
    )
    assert result.moisture_warning is False


def test_moisture_stress_none_on_susceptible_soil():
    """soil_water_balance stress='none' indicates surplus water."""
    result = evaluate_compaction_risk(
        soil_susceptibility_score=70,
        soil_susceptibility_class="high",
        soil_moisture_stress="none",
    )
    assert result.moisture_warning is True
    assert "moist_soil_susceptible" in result.contributing_factors


# ── Multi-year vigor ──

def test_persistent_low_vigor_triggers_concern():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=65,
        soil_susceptibility_class="high",
        vigor_anomaly_multiyear=-0.18,
        vigor_anomaly_years=3,
    )
    assert result.vigor_concern is True
    assert "persistent_low_vigor_3y" in result.contributing_factors
    assert result.requires_field_verification is True
    assert result.advisory == "compaction.advisory.verify_compaction_field"


def test_mild_vigor_anomaly_no_concern():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=40,
        soil_susceptibility_class="moderate",
        vigor_anomaly_multiyear=-0.07,
        vigor_anomaly_years=2,
    )
    assert result.vigor_concern is False
    assert "mild_persistent_low_vigor_2y" in result.contributing_factors


def test_single_season_vigor_ignored():
    """Need at least 2 seasons for multi-year analysis."""
    result = evaluate_compaction_risk(
        soil_susceptibility_score=65,
        soil_susceptibility_class="high",
        vigor_anomaly_multiyear=-0.20,
        vigor_anomaly_years=1,
    )
    assert result.vigor_concern is False
    assert len(result.contributing_factors) == 0  # single season = ignored


# ── Combined factors ──

def test_combined_wet_plus_low_vigor_on_high_susceptibility():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=72,
        soil_susceptibility_class="very_high",
        soil_moisture_pct=30.0,
        vigor_anomaly_multiyear=-0.15,
        vigor_anomaly_years=3,
    )
    # Base: 72*0.5=36 + moisture 15 + vigor 15 = 66 → high
    assert result.risk_level == "high"
    assert result.moisture_warning is True
    assert result.vigor_concern is True
    assert result.requires_field_verification is True
    # moisture_warning takes priority over vigor_concern in advisory
    assert result.advisory == "compaction.advisory.avoid_traffic_wet_soil"


# ── Traffic exposure ──

def test_high_traffic_on_susceptible_soil():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=70,
        soil_susceptibility_class="high",
        traffic_intensity=0.8,
    )
    assert result.traffic_exposure == "high"
    assert "high_traffic_exposure" in result.contributing_factors
    # Base: 35 + 12 = 47 → moderate
    assert result.risk_score >= 47


def test_traffic_unknown_when_none_provided():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=50,
        soil_susceptibility_class="moderate",
    )
    assert result.traffic_exposure == "unknown"


# ── Score boundaries ──

def test_score_never_exceeds_100():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=85,
        soil_susceptibility_class="very_high",
        soil_moisture_pct=40.0,
        vigor_anomaly_multiyear=-0.30,
        vigor_anomaly_years=5,
        traffic_intensity=1.0,
    )
    assert result.risk_score <= 100.0


def test_score_stays_non_negative():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=5,
        soil_susceptibility_class="very_low",
    )
    assert result.risk_score >= 0.0


# ── Advisory keys ──

def test_high_risk_without_moisture_or_vigor_advisory():
    """High risk from susceptibility alone → monitor advisory."""
    result = evaluate_compaction_risk(
        soil_susceptibility_score=80,
        soil_susceptibility_class="very_high",
        traffic_intensity=0.9,
    )
    assert result.risk_level in ("high", "very_high")
    assert result.advisory == "compaction.advisory.monitor_susceptible_soil"


def test_normal_management_advisory_for_low_risk():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=15,
        soil_susceptibility_class="very_low",
    )
    assert result.advisory == "compaction.advisory.normal_management"


# ── Return type completeness ──

def test_result_has_all_expected_fields():
    result = evaluate_compaction_risk(
        soil_susceptibility_score=50,
        soil_susceptibility_class="moderate",
    )
    for attr in ("risk_level", "risk_score", "susceptibility_score",
                 "contributing_factors", "moisture_warning", "vigor_concern",
                 "traffic_exposure", "advisory", "requires_field_verification",
                 "data_fidelity"):
        assert hasattr(result, attr), f"Missing attribute: {attr}"
