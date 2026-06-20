# tests/test_action_rules_engine.py
from app.engines.action_rules import evaluate_conditions

CTX = {"crop": {"role": "cover_crop", "status": "active"},
       "phenology": {"current_stage": "flowering", "deviation": "on_track"},
       "weather": {"temp_air": 22.0}}


def test_all_match():
    cond = {"all": [{"field": "crop.role", "op": "eq", "value": "cover_crop"},
                    {"field": "phenology.current_stage", "op": "eq", "value": "flowering"}]}
    assert evaluate_conditions(cond, CTX) is True


def test_all_one_fails():
    cond = {"all": [{"field": "crop.role", "op": "eq", "value": "main_crop"}]}
    assert evaluate_conditions(cond, CTX) is False


def test_any():
    cond = {"any": [{"field": "crop.role", "op": "eq", "value": "x"},
                    {"field": "crop.status", "op": "eq", "value": "active"}]}
    assert evaluate_conditions(cond, CTX) is True


def test_ops_in_between_gte():
    assert evaluate_conditions({"field": "phenology.deviation", "op": "in",
                                "value": ["on_track", "ahead"]}, CTX) is True
    assert evaluate_conditions({"field": "weather.temp_air", "op": "between",
                                "value": [18, 25]}, CTX) is True
    assert evaluate_conditions({"field": "weather.temp_air", "op": "gte", "value": 30}, CTX) is False


def test_unknown_field_or_missing_is_false_never_raises():
    assert evaluate_conditions({"field": "soil.field_capacity", "op": "gt", "value": 0.3}, CTX) is False
    assert evaluate_conditions({"field": "nope.nope", "op": "eq", "value": 1}, CTX) is False
