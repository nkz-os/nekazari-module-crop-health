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
