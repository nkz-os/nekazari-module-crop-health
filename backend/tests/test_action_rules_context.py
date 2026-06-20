# tests/test_action_rules_context.py
from datetime import date
from app.engines.action_rules import build_context

SEG = {"role": "cover_crop", "status": "active", "species": "Vicia sativa",
       "terminationMethod": "roller_crimper", "plantingDate": "2025-11-10",
       "sowingWindowStart": "2026-04-10"}
PHEN = {"currentStage": "flowering", "deviation": "on_track", "seasonStart": "2025-11-10",
        "gdd": {"accumulated": 742.0},
        "stages": [{"stage": "flowering", "current": True, "projectedEnd": "2026-03-15"}]}


def test_maps_crop_and_nested_phenology():
    ctx = build_context(SEG, PHEN, weather=None, soil=None, ndvi=0.55, stress=None, today=date(2026, 3, 1))
    assert ctx["crop"]["role"] == "cover_crop"
    assert ctx["crop"]["termination_method"] == "roller_crimper"
    assert ctx["phenology"]["current_stage"] == "flowering"
    assert ctx["phenology"]["gdd_accumulated"] == 742.0           # nested gdd.accumulated → flat
    assert ctx["phenology"]["stage_projected_end"] == "2026-03-15"  # from stages[current].projectedEnd
    assert ctx["vegetation"]["ndvi"] == 0.55
    assert ctx["crop"]["days_since_planting"] == (date(2026, 3, 1) - date(2025, 11, 10)).days


def test_missing_sources_yield_none_not_crash():
    ctx = build_context({"role": "main_crop", "status": "planned"}, {}, None, None, None, None, date(2026, 1, 1))
    assert ctx["phenology"]["gdd_accumulated"] is None
    assert ctx["weather"]["temp_air"] is None
    assert ctx["vegetation"]["ndvi"] is None
