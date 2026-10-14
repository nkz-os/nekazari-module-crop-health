"""The yield gap keeps its utilization %, and never kg/ha (spec D2/D7)."""
import app.services.context_client as cc
from app.engines.yield_gap import evaluate_yield_gap


def test_baseline_function_removed():
    assert not hasattr(cc, "get_variety_yield_baseline")


def test_gap_without_baseline_has_pct_and_no_kg():
    r = evaluate_yield_gap(cwsi_by_stage={"flowering": 0.4}, ky_by_stage={"flowering": 1.0})
    assert 0 < r.yield_utilization_pct < 100
    assert r.predicted_yield_kg_ha is None and r.baseline_yield_kg_ha is None
