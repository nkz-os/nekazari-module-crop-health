"""One water-stress level: resolution, cuts, severity, composite, event, Orion attrs."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines import water_stress_level as wsl
from app.engines.composite import evaluate_composite_stress
from app.engines.water_stress_level import (
    CWSI_CUTS, KS_INDEX_CUTS, WaterStressIndicator, resolve_indicator,
)
from app.schemas import (
    CropHealthAssessment, CWSIResult, CwsiBaseline, Severity, StageWaterFlags,
    WaterBalanceResult, WaterStress, WaterStressReference,
)
from app.services import pipeline

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _cwsi(v, baseline_id="b1"):
    return CWSIResult(cwsi=v, vpd_kpa=3.0, temp_canopy=30.0, temp_air=35.0, d1=-2.0, d2=2.0,
                      baseline_id=baseline_id)


def _ws(index):
    return WaterStress(index=index, fidelity="parcel_weather", observed_at=None, shade_fraction=None)


def _flags(sensitive=True, rdi=None, sources=("srcF",)):
    return StageWaterFlags.model_validate(
        {"waterSensitive": sensitive, "rdiTolerant": rdi, "sourceIds": list(sources)})


def _assessment(**kw):
    return CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, **kw)


def test_sensor_cwsi_wins_over_balance():
    ind = resolve_indicator(_cwsi(0.45), _ws(0.9), None)
    assert (ind.level, ind.method, ind.value, ind.baseline_id) == ("moderate", "cwsi_sensor", 0.45, "b1")


def test_balance_when_no_cwsi():
    ind = resolve_indicator(None, _ws(0.3), None)
    assert (ind.level, ind.method, ind.value) == ("moderate", "balance", 0.3)


def test_no_inputs_is_no_data_not_none():
    for ws in (None, _ws(None)):
        ind = resolve_indicator(None, ws, None)
        assert (ind.level, ind.method, ind.value) == ("no_data", "none", None)


def test_not_needed_stage_overrides_level():
    ind = resolve_indicator(_cwsi(0.9), None, _flags(False, sources=("srcF",)))
    assert ind.level == "not_needed" and ind.method == "cwsi_sensor" and ind.source_ids == ("srcF",)
    assert resolve_indicator(None, None, _flags(False)).level == "not_needed"


def test_rdi_stage_keeps_level_adds_note():
    ind = resolve_indicator(_cwsi(0.45), None, _flags(True, rdi=True))
    assert ind.level == "moderate" and ind.phase_note == "rdi" and "srcF" in ind.source_ids
    assert resolve_indicator(_cwsi(0.05), None, _flags(True, rdi=True)).phase_note is None


def test_unknown_stage_flags_no_note():
    for flags in (None, _flags("unknown")):
        ind = resolve_indicator(_cwsi(0.45), None, flags)
        assert ind.level == "moderate" and ind.phase_note is None
    assert resolve_indicator(_cwsi(0.45), None, _flags("unknown")).source_ids == ()


def test_sources_from_baseline_via_reference():
    ref = WaterStressReference(baselines=[CwsiBaseline.model_validate({
        "id": "b1", "a0C": 3.38, "a1CPerKpa": -3.25, "sourceId": "srcB",
        "upper": {"form": "constant", "valueC": 1.0},
        "valid": {"solarHourFrom": 10, "solarHourTo": 16, "clearSky": True}})])
    assert resolve_indicator(_cwsi(0.3), None, None, reference=ref).source_ids == ("srcB",)


@pytest.mark.parametrize("v,level", [
    (0.0, "none"), (0.1999, "none"), (0.2, "mild"), (0.3999, "mild"),
    (0.4, "moderate"), (0.5999, "moderate"), (0.6, "high"), (1.0, "high"),
])
def test_cwsi_cut_boundaries(v, level):
    assert resolve_indicator(_cwsi(v), None, None).level == level


@pytest.mark.parametrize("ks,level", [
    (1.0, "none"), (0.95, "none"), (0.949, "mild"), (0.80, "mild"), (0.799, "moderate"),
    (0.50, "moderate"), (0.499, "high"), (0.0, "high"),
])
def test_ks_cut_boundaries(ks, level):
    # index as the pipeline builds it: round(1 - Ks, 3)
    assert resolve_indicator(None, _ws(round(1 - ks, 3)), None).level == level


def test_cuts_single_source():
    assert CWSI_CUTS == {"mild": 0.2, "moderate": 0.4, "high": 0.6}
    assert KS_INDEX_CUTS == {"none_ks_min": 0.95, "mild_ks_min": 0.80, "moderate_ks_min": 0.50}
    # severity reads the level resolved from these cuts, with no cut of its own
    for v, sev in ((0.19, Severity.LOW), (0.2, Severity.MEDIUM), (0.4, Severity.HIGH), (0.6, Severity.CRITICAL)):
        assert pipeline._determine_overall_severity(_assessment(cwsi=_cwsi(v))) == sev
    src = open(pipeline.__file__).read()
    assert "0.7" not in src[src.index("def _determine_overall_severity"):src.index("def _determine_action")]
    assert wsl.severity_name("no_data") is None


def test_no_data_adds_no_severity():
    a = _assessment(water_stress_indicator=WaterStressIndicator("no_data", "none"))
    assert pipeline._determine_overall_severity(a) == Severity.LOW


def _dry_not_needed():
    return _assessment(
        cwsi=_cwsi(0.9),
        water_balance=WaterBalanceResult(balance_mm=-30.0, precip_mm=0, etc_mm=5, kc=1.0, deficit=True),
        water_stress_indicator=resolve_indicator(_cwsi(0.9), None, _flags(False)),
    )


def test_not_needed_severity_low_even_with_dry_soil():
    assert pipeline._determine_overall_severity(_dry_not_needed()) == Severity.LOW


@pytest.mark.asyncio
async def test_no_breach_event_in_not_needed(monkeypatch):
    events = []

    async def _pub(stream, event):
        events.append(event)

    monkeypatch.setattr(pipeline, "_publish_redis_event", _pub)
    a = _dry_not_needed()
    a.overall_severity = pipeline._determine_overall_severity(a)
    await pipeline._emit_assessment_side_effects(a, "tenant-a", NOW, "maturity")
    assert [e["event_type"] for e in events] == ["crop.assessment.completed"]
    # a real breach still fires
    events.clear()
    b = _assessment(cwsi=_cwsi(0.7))
    b.overall_severity = pipeline._determine_overall_severity(b)
    await pipeline._emit_assessment_side_effects(b, "tenant-a", NOW, "vegetative")
    assert "crop.stress.breach" in [e["event_type"] for e in events]


def test_composite_water_zero_in_not_needed():
    base = evaluate_composite_stress(cwsi=0.9, water_balance_mm=-30.0, stage="vegetative")
    off = evaluate_composite_stress(cwsi=0.9, water_balance_mm=-30.0, stage="vegetative", water_not_needed=True)
    assert base.water_contribution > 0 and off.water_contribution == 0.0
    th = evaluate_composite_stress(cwsi=0.9, thermal_severity="HIGH", water_not_needed=True)
    assert th.thermal_contribution == 35.0 and th.dominant_stressor == "thermal"


def test_orion_attrs_written_and_cleared():
    a = _assessment(water_stress_indicator=WaterStressIndicator(
        "moderate", "cwsi_sensor", 0.45, "rdi", "b1", ("s1", "s2")))
    e = a.to_ngsi_ld()
    assert e["waterStressLevel"]["value"] == "moderate"
    assert e["waterStressMethod"]["value"] == "cwsi_sensor"
    assert e["waterStressPhaseNote"]["value"] == "rdi"
    assert e["waterStressReferenceSources"]["value"] == ["s1", "s2"]
    # no note, no sources: list is empty and the note attribute is absent (-> cleared)
    e2 = _assessment(water_stress_indicator=WaterStressIndicator("none", "balance", 0.0)).to_ngsi_ld()
    assert e2["waterStressReferenceSources"]["value"] == [] and "waterStressPhaseNote" not in e2
    for attr in ("waterStressLevel", "waterStressMethod", "waterStressPhaseNote", "waterStressReferenceSources"):
        assert attr in pipeline._WATER_STRESS_OPTIONAL_ATTRS


def test_mapper_exposes_fields():
    from app.api.assessment_mapper import map_entity_to_assessment

    e = _assessment(water_stress_indicator=WaterStressIndicator(
        "mild", "balance", 0.1, None, None, ("s1",))).to_ngsi_ld()
    m = map_entity_to_assessment(e)
    assert m["waterStressLevel"] == "mild" and m["waterStressMethod"] == "balance"
    assert m["waterStressPhaseNote"] is None and m["waterStressReferenceSources"] == ["s1"]
