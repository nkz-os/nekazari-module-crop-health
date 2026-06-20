"""Pure rule-condition engine (no I/O). Never raises — False on unknown field/op."""
from __future__ import annotations


def _resolve_field(field: str, ctx: dict):
    cur = ctx
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _compare(actual, op: str, value) -> bool:
    try:
        if op == "eq":   return actual == value
        if op == "neq":  return actual != value
        if op == "gt":   return actual > value
        if op == "gte":  return actual >= value
        if op == "lt":   return actual < value
        if op == "lte":  return actual <= value
        if op == "in":   return actual in value
        if op == "between": return value[0] <= actual <= value[1]
        if op == "exists":  return (actual is not None) == bool(value)
    except (TypeError, ValueError, IndexError):
        return False
    return False


def evaluate_conditions(conditions: dict, ctx: dict) -> bool:
    if not isinstance(conditions, dict):
        return False
    if "all" in conditions:
        return all(evaluate_conditions(c, ctx) for c in conditions["all"])
    if "any" in conditions:
        return any(evaluate_conditions(c, ctx) for c in conditions["any"])
    actual = _resolve_field(conditions.get("field", ""), ctx)
    if actual is None and conditions.get("op") != "exists":
        return False
    return _compare(actual, conditions.get("op", "eq"), conditions.get("value"))


def _days_between(d_from: str | None, d_to) -> int | None:
    from datetime import date as _d
    if not d_from:
        return None
    try:
        return (d_to - _d.fromisoformat(str(d_from)[:10])).days
    except (TypeError, ValueError):
        return None


def _current_projected_end(phenology: dict):
    for s in (phenology.get("stages") or []):
        if s.get("current"):
            return s.get("projectedEnd")
    return None


def build_context(seg, phenology, weather, soil, ndvi, stress, today) -> dict:
    seg = seg or {}
    phenology = phenology or {}
    gdd = (phenology.get("gdd") or {}).get("accumulated") if isinstance(phenology.get("gdd"), dict) else None
    ws = lambda k: getattr(weather, k, None) if weather is not None and not isinstance(weather, dict) else (weather or {}).get(k)
    sp = lambda k: getattr(soil, k, None) if soil is not None and not isinstance(soil, dict) else (soil or {}).get(k)
    fc, wp = sp("field_capacity"), sp("wilting_point")
    return {
        "crop": {
            "role": seg.get("role"), "status": seg.get("status"), "species": seg.get("species"),
            "termination_method": seg.get("terminationMethod"),
            "days_since_planting": _days_between(seg.get("plantingDate"), today),
            "days_until_sowing_window": (lambda d: -d if d is not None else None)(_days_between(seg.get("sowingWindowStart"), today)),
        },
        "phenology": {
            "current_stage": phenology.get("currentStage"), "deviation": phenology.get("deviation"),
            "season_start": phenology.get("seasonStart"), "gdd_accumulated": gdd,
            "stage_projected_end": _current_projected_end(phenology),
        },
        "weather": {"temp_air": ws("temp_air") or ws("temperature"), "eto_mm": ws("eto_mm") or ws("eto"),
                    "precip_mm_7d": ws("precip_mm_7d"), "frost_risk": ws("frost_risk")},
        "soil": {"field_capacity": fc, "wilting_point": wp,
                 "available_water": (fc - wp) if (fc is not None and wp is not None) else None},
        "vegetation": {"ndvi": ndvi, "ndvi_anomaly": None},
        "stress": {
            "composite_index": (stress or {}).get("composite_index"),
            "dominant_stressor": (stress or {}).get("dominant_stressor"),
            "condition": (stress or {}).get("condition"),
        },
    }
