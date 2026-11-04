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


# ── Rollups: the level is resolved again once the parcel Ks exists ──────────

def _rollup(ws_index, *, stage="maturity", gdd=900.0, sev=Severity.LOW, flags=None, wb=None):
    ref = WaterStressReference.model_validate({
        "baselines": [],
        "stages": {stage: {"waterSensitive": flags, "sourceIds": ["srcF"]}} if flags is not None else {},
    })
    a = _assessment(
        water_stress=_ws(ws_index), phenology_stage=stage, gdd_accumulated=gdd,
        water_stress_indicator=WaterStressIndicator("no_data", "none"),
        overall_severity=sev, water_balance=wb,
    )
    return a, types_ns(ref)


def types_ns(ref):
    import types
    return types.SimpleNamespace(water_stress_reference=ref)


def test_rollup_level_follows_ks_index():
    a, ph = _rollup(0.358)
    pipeline._refresh_rollup_level(a, ph)
    assert (a.water_stress_indicator.level, a.water_stress_indicator.method) == ("moderate", "balance")
    assert a.overall_severity == Severity.HIGH and a.recommended_action.value == "IRRIGATE_SCHEDULED"


def test_rollup_keeps_worse_zone_severity():
    a, ph = _rollup(0.0, sev=Severity.CRITICAL)
    pipeline._refresh_rollup_level(a, ph)
    assert a.water_stress_indicator.level == "none" and a.overall_severity == Severity.CRITICAL


def test_rollup_sensor_cwsi_level_is_final():
    a, ph = _rollup(0.9)
    a.cwsi = _cwsi(0.1)
    a.water_stress_indicator = resolve_indicator(a.cwsi, None, None)
    pipeline._refresh_rollup_level(a, ph)
    assert a.water_stress_indicator.method == "cwsi_sensor" and a.overall_severity == Severity.LOW


def test_rollup_not_needed_has_no_water_alarm():
    wb = WaterBalanceResult(balance_mm=-30.0, precip_mm=0, etc_mm=5, kc=1.0, deficit=True)
    a, ph = _rollup(0.9, sev=Severity.CRITICAL, flags=False, wb=wb)
    pipeline._refresh_rollup_level(a, ph)
    assert a.water_stress_indicator.level == "not_needed"
    assert a.overall_severity == Severity.LOW and a.recommended_action.value == "NO_ACTION"


def test_rollup_without_gdd_ignores_stage_flags():
    a, ph = _rollup(0.9, gdd=None, flags=False)
    pipeline._refresh_rollup_level(a, ph)
    assert a.water_stress_indicator.level == "high"


@pytest.mark.asyncio
async def test_scheduled_path_level_matches_ks(monkeypatch):
    from tests.test_pipeline_under_panel_stress import FakeRedis
    from tests.test_scheduled_daily_balance import TENANT, URN, _rollup_entity, _setup_scheduled
    published, _ = _setup_scheduled(monkeypatch, FakeRedis())
    await pipeline.compute_assessment(URN, TENANT)
    e = _rollup_entity(published)
    expected = wsl.level_from_index(e["waterStressIndex"]["value"])
    assert expected != "no_data"
    assert e["waterStressLevel"]["value"] == expected
    assert e["waterStressMethod"]["value"] == "balance"


@pytest.mark.asyncio
async def test_zonal_trigger_breach_from_recomputed_severity(monkeypatch):
    from app.services.zonation import Zone
    from tests.test_pipeline_under_panel_stress import (
        _Z0, _Z1, FakeRedis, _setup, _trigger, soil_reading,
    )
    events = []

    async def _pub(stream, event):
        events.append(event)

    real_emit = pipeline._emit_assessment_side_effects  # captured before the harness stubs it
    published, _ = _setup(monkeypatch, zones=[Zone("z0", _Z0), Zone("z1", _Z1)])
    monkeypatch.setattr(pipeline, "_emit_assessment_side_effects", real_emit)
    monkeypatch.setattr(pipeline, "_publish_redis_event", _pub)

    async def _nocoords(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_coords", _nocoords, raising=False)
    # very dry probe -> Ks index high on the rollup; zones themselves carry no Ks
    out = await _trigger(FakeRedis(readings={"soilMoisture": [soil_reading(8.0)]}))
    assert out.water_stress_indicator.level in ("moderate", "high")
    assert out.overall_severity in (Severity.HIGH, Severity.CRITICAL)
    assert "crop.stress.breach" in [e["event_type"] for e in events]
