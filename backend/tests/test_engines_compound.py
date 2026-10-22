"""Test compound engines: composite stress, yield gap, thermal, vigor."""
import pytest
from app.engines.composite import evaluate_composite_stress, CompositeStressResult
from app.engines.yield_gap import evaluate_yield_gap, YieldGapResult
from app.engines.thermal_stress import evaluate_thermal_stress, ThermalResult
from app.engines.vigor import evaluate_vigor, VigorResult


class TestCompositeStress:
    def test_no_stress(self):
        result = evaluate_composite_stress(cwsi=0.1, stage="vegetative")
        assert result.condition == "no_stress"
        assert result.composite_index < 25

    def test_severe_stress(self):
        result = evaluate_composite_stress(cwsi=0.8, mds_ratio=1.6, stage="flowering")
        assert result.condition == "severe"
        assert result.composite_index > 50

    def test_ky_weighting(self):
        vegetative = evaluate_composite_stress(cwsi=0.5, stage="vegetative")
        flowering = evaluate_composite_stress(cwsi=0.5, stage="flowering")
        # Flowering has higher Ky (1.15) than vegetative (0.45), so same CWSI = more stress
        assert flowering.water_contribution > vegetative.water_contribution

    def test_dominant_stressor(self):
        result = evaluate_composite_stress(cwsi=0.7, thermal_severity="LOW", vigor_index=0.8)
        assert result.dominant_stressor == "water"


class TestYieldGap:
    def test_full_potential(self):
        result = evaluate_yield_gap(cwsi_by_stage={"vegetative": 0.0}, ky_by_stage={"vegetative": 0.45})
        assert result.yield_utilization_pct > 90

    def test_water_stress_loss(self):
        result = evaluate_yield_gap(cwsi_by_stage={"flowering": 0.6}, ky_by_stage={"flowering": 1.15})
        assert result.yield_utilization_pct < 80  # loss due to high CWSI × high Ky

    def test_empty_input(self):
        result = evaluate_yield_gap(cwsi_by_stage={}, ky_by_stage={})
        assert result.confidence == "low"
        assert result.yield_utilization_pct == 100.0


class TestThermal:
    def test_no_stress(self):
        result = evaluate_thermal_stress(leaf_temp=25.0, air_temp=22.0, air_temp_min_24h=5.0)
        assert result.condition == "no_stress"

    def test_heat_stress(self):
        result = evaluate_thermal_stress(leaf_temp=38.0, air_temp=30.0)
        assert "heat" in result.condition

    def test_frost_damage(self):
        result = evaluate_thermal_stress(leaf_temp=None, air_temp=-3.0, air_temp_min_24h=-4.0)
        assert "frost" in result.condition


class TestVigor:
    def test_healthy_vigor(self):
        result = evaluate_vigor(ndvi=0.8, cwsi=0.1, stage="vegetative")
        assert result.vigor_index > 0.5
        assert result.index_used in ("GNDVI", "NDVI")

    def test_stressed_vigor(self):
        result = evaluate_vigor(ndvi=0.4, cwsi=0.7, stage="vegetative")
        assert result.vigor_index < 0.5

    def test_auto_select_savi(self):
        result = evaluate_vigor(savi=0.5, ndvi=0.5, stage="emergence")
        assert result.index_used == "SAVI"

    def test_anomaly_detection(self):
        result = evaluate_vigor(ndvi=0.3, expected_ndvi=0.6, stage="vegetative")
        assert result.condition == "below_expected"
