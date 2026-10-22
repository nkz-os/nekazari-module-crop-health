from app.engines.phenology_progress import derive_stage_from_gdd, evaluate_phenology_progress

TH = {"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0),
      "flowering": (520.0, 1100.0), "maturity": (1100.0, 1600.0)}


def test_within_range():
    assert derive_stage_from_gdd(300.0, TH) == "vegetative"

def test_lower_bound_inclusive():
    assert derive_stage_from_gdd(90.0, TH) == "vegetative"

def test_below_first_clamps_to_first():
    assert derive_stage_from_gdd(-5.0, TH) == "emergence"

def test_at_or_above_last_clamps_to_final():
    assert derive_stage_from_gdd(5000.0, TH) == "maturity"

def test_empty_thresholds_unknown():
    assert derive_stage_from_gdd(300.0, {}) == "unknown"

def test_deviation_ahead_uses_gdd_order_not_alphabetical():
    # declared 'emergence' but GDD is in 'flowering' → ahead by GDD order.
    # Verified against the original implementation: it returned 'behind' here
    # (its `stage_name > current_stage` branch fires for 'flowering' > 'emergence'),
    # which is wrong — flowering comes strictly after emergence in GDD order.
    r = evaluate_phenology_progress(600.0, "emergence", TH)
    assert r.deviation == "ahead"

def test_deviation_behind_alphabetical_trap():
    # declared 'maturity' (last stage), GDD in 'flowering' (an earlier stage) → behind.
    # Alphabetically 'flowering' < 'maturity', which the OLD code read as "ahead"
    # (its `stage_name > current_stage` branch is False here) — the real alphabetical
    # trap: verified against the original implementation (old gives 'ahead', wrong;
    # by GDD order flowering precedes maturity, so the correct answer is 'behind').
    r = evaluate_phenology_progress(800.0, "maturity", TH)
    assert r.deviation == "behind"
