"""The level travels everywhere: events (I3), mapper (I4, I5), zone entities (I6), irrigation."""
from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from app.api.assessment_mapper import map_entity_to_assessment
from app.engines.water_stress_level import WaterStressIndicator, level_from_index, resolve_indicator
from app.schemas import (
    CropHealthAssessment, CWSIResult, Severity, SoilWaterBalanceResult, StageWaterFlags,
    WaterStress, WaterStressReference,
)
from app.services import pipeline

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _a(**kw):
    return CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, **kw)


def _flags(sensitive=True, rdi=None):
    return StageWaterFlags.model_validate({"waterSensitive": sensitive, "rdiTolerant": rdi, "sourceIds": ["f"]})


def _ws(index):
    return WaterStress(index=index, fidelity="parcel_weather", observed_at=None, shade_fraction=None)


# ── I3: events carry the level ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_carry_level_method_and_note(monkeypatch):
    events = []

    async def _pub(stream, event):
        events.append(event)

    monkeypatch.setattr(pipeline, "_publish_redis_event", _pub)
    a = _a(water_stress_indicator=WaterStressIndicator("high", "balance", 0.6, "rdi"))
    a.overall_severity = Severity.CRITICAL
    await pipeline._emit_assessment_side_effects(a, "tenant-a", NOW, "veraison")
    by_type = {e["event_type"]: e for e in events}
    for name in ("crop.assessment.completed", "crop.stress.breach"):
        e = by_type[name]
        assert e["water_stress_level"] == "high"
        assert e["water_stress_method"] == "balance"
        assert e["water_stress_phase_note"] == "rdi"

    events.clear()
    await pipeline._emit_assessment_side_effects(_a(), "tenant-a", NOW, "vegetative")
    e = events[0]
    assert e["water_stress_level"] == "no_data" and e["water_stress_method"] == "none"
    assert e["water_stress_phase_note"] is None


# ── I4 / I5: mapper ──────────────────────────────────────────────────────────

def _cwsi():
    return CWSIResult(cwsi=0.5, vpd_kpa=3.2, temp_canopy=30.0, temp_air=28.0, d1=-1.0, d2=1.0)


def test_mapper_exposes_vpd():
    m = map_entity_to_assessment(_a(cwsi=_cwsi()).to_ngsi_ld())
    assert m["vpdKpa"] == 3.2
    assert map_entity_to_assessment(_a().to_ngsi_ld())["vpdKpa"] is None


@pytest.mark.parametrize("stored, expected", [
    ("fao56", ["fao56"]),          # Orion compacts a one-element array to its value
    (["a", "b"], ["a", "b"]),
    ([], []),
    (None, []),
])
def test_mapper_reference_sources_always_a_list(stored, expected):
    e = _a(water_stress_indicator=WaterStressIndicator("mild", "balance", 0.1)).to_ngsi_ld()
    if stored is None:
        e.pop("waterStressReferenceSources")
    else:
        e["waterStressReferenceSources"] = {"type": "Property", "value": stored}
    assert map_entity_to_assessment(e)["waterStressReferenceSources"] == expected


# ── I6: zones take the parcel balance with their own stage flags ─────────────

def _zone(zid, flags=None, *, method="none", sev=Severity.LOW):
    z = _a(zone_id=zid, overall_severity=sev,
           water_stress_indicator=resolve_indicator(None, None, flags))
    if method == "cwsi_sensor":
        z.cwsi = CWSIResult(cwsi=0.1, vpd_kpa=3.0, temp_canopy=30.0, temp_air=31.0, d1=-1.0, d2=1.0)
        z.water_stress_indicator = resolve_indicator(z.cwsi, None, flags)
    z.water_stress_stage_flags = flags
    return z


def test_zones_without_cwsi_take_the_parcel_balance():
    rollup = _a(water_stress=_ws(0.6))
    zones = [
        _zone("z0"),
        _zone("z1", _flags(sensitive=False)),
        _zone("z2", _flags(rdi=True)),
        _zone("z3", method="cwsi_sensor"),
    ]
    pipeline._apply_parcel_balance_to_zones(zones, rollup, types.SimpleNamespace(water_stress_reference=None))
    z0, z1, z2, z3 = (z.water_stress_indicator for z in zones)
    assert (z0.level, z0.method) == (level_from_index(0.6), "balance") == ("high", "balance")
    assert zones[0].overall_severity == Severity.CRITICAL
    assert (z1.level, z1.method) == ("not_needed", "balance") and zones[1].overall_severity == Severity.LOW
    assert (z2.level, z2.phase_note) == ("high", "rdi")
    assert z3.method == "cwsi_sensor" and z3.level == "none"
    # zone entities publish it
    e = zones[0].to_zone_ngsi_ld()
    assert e["waterStressLevel"]["value"] == "high" and e["waterStressMethod"]["value"] == "balance"


def test_no_parcel_balance_keeps_zones_no_data():
    zones = [_zone("z0")]
    pipeline._apply_parcel_balance_to_zones(zones, _a(), None)
    assert zones[0].water_stress_indicator.level == "no_data"


def test_stage_flags_are_kept_on_the_assessment_not_published():
    z = _zone("z0", _flags(rdi=True))
    assert "water_stress_stage_flags" not in str(z.to_zone_ngsi_ld())


@pytest.mark.asyncio
async def test_zonal_trigger_zone_entities_show_the_parcel_balance(monkeypatch):
    from app.services.zonation import Zone
    from tests.test_pipeline_under_panel_stress import _Z0, _Z1, FakeRedis, _setup, _trigger, soil_reading

    published, _ = _setup(monkeypatch, zones=[Zone("z0", _Z0), Zone("z1", _Z1)])

    async def _nocoords(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_coords", _nocoords, raising=False)
    out = await _trigger(FakeRedis(readings={"soilMoisture": [soil_reading(8.0)]}))
    zone_entities = [e for e in published["entities"] if e["type"] == "CropHealthZoneAssessment"]
    assert len(zone_entities) == 2
    for e in zone_entities:
        assert e["waterStressMethod"]["value"] == "balance"
        assert e["waterStressLevel"]["value"] == out.water_stress_indicator.level != "no_data"
    # zones are published before the rollup
    types_ = [e["type"] for e in published["entities"]]
    assert types_.index("CropHealthAssessment") > max(i for i, t in enumerate(types_) if t == "CropHealthZoneAssessment")


# ── minor: no irrigation advice in a stage that needs no water ───────────────

def _swb(stress="high"):
    return SoilWaterBalanceResult(
        sw_mm=20.0, awc_mm=100.0, sw_ratio=0.2, raw_mm=50.0, deficit_mm=80.0, excess_mm=0.0,
        stress_level=stress, actual_et_mm=1.0, deep_percolation_mm=0.0, depletion_fraction_p=0.5,
        stress_coefficient_ks=0.4, soil_moisture_confidence="low",
    )


def test_irrigation_none_when_water_not_needed():
    r = pipeline._crop_requirements(_a(
        soil_water_balance=_swb(), water_stress_indicator=WaterStressIndicator("not_needed", "balance", 0.6)))
    assert r.irrigation_mm is None and r.water_deficit_mm == 80.0
    r = pipeline._crop_requirements(_a(
        soil_water_balance=_swb(), water_stress_indicator=WaterStressIndicator("high", "balance", 0.6)))
    assert r.irrigation_mm == 80.0
    r = pipeline._crop_requirements(_a())
    assert r.irrigation_mm is None and r.water_deficit_mm is None
