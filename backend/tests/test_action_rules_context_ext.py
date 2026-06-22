"""Tests for SP2 build_context irrigation/NPK extension."""
from datetime import date
from app.engines.action_rules import build_context


def test_build_context_includes_irrigation():
    crop_req = {"waterDeficitMm": 35.0, "nRequirementKgHa": 45.0, "p2o5RequirementKgHa": 20.0}
    ctx = build_context({}, {}, None, None, None, None, date.today(), crop_requirements=crop_req)
    assert ctx.get("water_deficit_mm") == 35.0
    assert ctx.get("n_requirement_kg_ha") == 45.0
    assert ctx.get("p_requirement_kg_ha") == 20.0


def test_build_context_no_crop_requirements():
    ctx = build_context({}, {}, None, None, None, None, date.today())
    assert ctx.get("water_deficit_mm") is None
    assert ctx.get("n_requirement_kg_ha") is None
