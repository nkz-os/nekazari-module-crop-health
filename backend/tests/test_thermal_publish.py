"""The thermal result is published only when something was evaluated, and adds nothing when calm."""
import pytest

from app.schemas import CropHealthAssessment, ThermalStressResult
from app.services import pipeline
from tests.test_scheduled_daily_balance import TENANT, URN, FakeRedis, _rollup_entity, _setup_scheduled

THERMAL_ATTRS = ("thermalCondition", "thermalSeverity", "thermalDataFidelity", "heatStressHours", "frostHours")


@pytest.mark.asyncio
async def test_a_night_without_thermal_inputs_publishes_no_thermal_result(monkeypatch):
    published, _ = _setup_scheduled(monkeypatch, FakeRedis())
    out = await pipeline.compute_assessment(URN, TENANT)
    entity = _rollup_entity(published)
    assert out.thermal is None
    assert [a for a in THERMAL_ATTRS if a in entity] == []
    assert entity["compositeThermalContribution"]["value"] == 0
    assert entity["dominantStressor"]["value"] != "thermal"


def _entity(thermal):
    from datetime import datetime, timezone

    return CropHealthAssessment(parcel_id="p1", assessed_at=datetime.now(timezone.utc), thermal=thermal).to_ngsi_ld()


def test_an_evaluated_result_carries_no_hours():
    entity = _entity(ThermalStressResult(condition="heat_stress", severity="CRITICAL", data_fidelity="onsite_uncalibrated"))
    assert entity["thermalCondition"]["value"] == "heat_stress"
    assert "heatStressHours" not in entity and "frostHours" not in entity


@pytest.mark.parametrize("condition,severity,expected", [
    ("no_stress", "LOW", None), ("heat_stress", "CRITICAL", "CRITICAL"), ("frost_warning", "MEDIUM", "MEDIUM")])
def test_only_a_stress_enters_the_composite_index(condition, severity, expected):
    assert pipeline.thermal_stress_severity(ThermalStressResult(condition=condition, severity=severity)) == expected


def test_no_thermal_result_does_not_enter_the_composite_index():
    assert pipeline.thermal_stress_severity(None) is None
