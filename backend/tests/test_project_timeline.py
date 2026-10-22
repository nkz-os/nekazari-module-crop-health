from datetime import date

from app.engines.phenology_progress import project_stage_timeline

TH = {"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0),
      "flowering": (520.0, 1100.0), "maturity": (1100.0, 1600.0)}


def test_marks_current_and_reached():
    out = project_stage_timeline(300.0, TH, mean_daily_gdd=10.0, today=date(2026, 6, 19))
    by = {s["stage"]: s for s in out}
    assert by["emergence"]["reached"] is True
    assert by["vegetative"]["current"] is True
    assert by["flowering"]["reached"] is False

def test_projects_future_stage_date():
    # gdd=300, flowering starts at 520 → 220 gdd away / 10 per day = 22 days
    out = project_stage_timeline(300.0, TH, mean_daily_gdd=10.0, today=date(2026, 6, 19))
    by = {s["stage"]: s for s in out}
    assert by["flowering"]["projectedDate"] == "2026-07-11"

def test_zero_mean_daily_gdd_no_projection_no_crash():
    out = project_stage_timeline(300.0, TH, mean_daily_gdd=0.0, today=date(2026, 6, 19))
    by = {s["stage"]: s for s in out}
    assert by["flowering"]["projectedDate"] is None

def test_empty_thresholds_returns_empty():
    assert project_stage_timeline(300.0, {}, 10.0, date(2026, 6, 19)) == []
