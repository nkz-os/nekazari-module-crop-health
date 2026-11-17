from datetime import date

from app.services import prediction_score as ps
from app.services.prediction_log import PredictionRecord

WL = {"basis": "water_limited", "unit": "t/ha", "range": None, "provider_id": "aquacrop",
      "percentiles": {"p10": 10.44, "p50": 11.83, "p90": 12.84},
      "moisture": {"pct": 13.0, "basis": "commercial"}, "validation": {"status": "not_applicable"}}
GC = {"basis": "gap_corrected", "unit": "t/ha", "range": {"low": 1.05, "high": 6.79}, "percentiles": None,
      "provider_id": "aquacrop", "moisture": {"pct": 13.0, "basis": "commercial"},
      "validation": {"status": "experimental"}}


def _cycle(start, end=None, weight=None, lifecycle="annual"):
    return {"crop_id": "c", "species": "TRZAX", "lifecycle": lifecycle,
            "start": {"date": start, "provenance": "actual"}, "end": {"date": end, "provenance": None},
            "harvested_weight_kg": weight}


def test_pick_cycle_exact_then_by_date_then_none():
    cycles = [_cycle(None), _cycle("2025-11-01", "2026-07-01"), _cycle("2026-10-20")]
    assert ps.pick_cycle(cycles, date(2026, 10, 20), None) == (cycles[2], "exact")
    assert ps.pick_cycle(cycles, date(2026, 10, 25), date(2026, 11, 15)) == (cycles[2], "by_date")
    assert ps.pick_cycle(cycles, date(2024, 1, 1), date(2024, 2, 1)) == (None, None)
    assert ps.pick_cycle([_cycle(None)], date(2026, 10, 20), date(2026, 11, 15)) == (None, None)


def test_observed_harvest_reasons_and_value():
    done = _cycle("2026-10-20", "2027-07-05", 40000.0)
    assert ps.observed_harvest(done, {"area": 8.0}) == ({
        "harvest_date": "2027-07-05", "weight_kg": 40000.0, "area_ha": 8.0, "yield_t_ha": 5.0,
        "basis": "as_delivered", "completeness": "unknown"}, None)
    assert ps.observed_harvest(None, {"area": 8.0}) == (None, "cycle_not_found")
    assert ps.observed_harvest(_cycle("2026-10-20"), {"area": 8.0}) == (None, "no_harvest_recorded")
    assert ps.observed_harvest(_cycle("2026-10-20", "2027-07-05", 0), {"area": 8.0}) == (None, "no_harvest_recorded")
    for bad in ({}, {"area": 0}, {"area": -1}, {"area": "8"}, {"area": True}, None):
        assert ps.observed_harvest(done, bad) == (None, "area_unavailable")
    per = _cycle("2020-01-01", None, 900.0, lifecycle="perennial")
    assert ps.observed_harvest(per, {"area": 8.0}) == (None, "perennial_not_supported")


def test_score_estimate_percentiles_and_range():
    wl = ps.score_estimate(WL, 5.0)
    assert (wl["p50"], wl["error_t_ha"], wl["error_pct"], wl["within_p10_p90"]) == (11.83, 6.83, 136.6, False)
    assert wl["within_range"] is None and wl["distance_to_range_t_ha"] is None
    assert (wl["validation_status"], wl["moisture_pct"], wl["basis"]) == ("not_applicable", 13.0, "water_limited")
    gc = ps.score_estimate(GC, 5.0)
    assert (gc["low"], gc["high"], gc["within_range"], gc["distance_to_range_t_ha"]) == (1.05, 6.79, True, 0.0)
    assert gc["error_t_ha"] is None and gc["within_p10_p90"] is None
    assert ps.score_estimate(GC, 7.5)["distance_to_range_t_ha"] == 0.71
    assert ps.score_estimate(GC, 0.5)["distance_to_range_t_ha"] == -0.55


def test_score_estimate_never_invents():
    assert ps.score_estimate(WL, None)["error_t_ha"] is None
    kg = dict(WL, unit="kg/ha")
    assert ps.score_estimate(kg, 5.0)["error_t_ha"] is None and ps.score_estimate(kg, 5.0)["p50"] == 11.83
    broken = dict(WL, percentiles={"p10": "x", "p50": None, "p90": True})
    out = ps.score_estimate(broken, 5.0)
    assert out["p50"] is None and out["error_t_ha"] is None and out["within_p10_p90"] is None
    empty = ps.score_estimate({"basis": "water_limited"}, 5.0)
    assert empty["p50"] is None and empty["low"] is None and empty["validation_status"] is None


def test_score_rows_lead_days_and_missing_estimates():
    rec = PredictionRecord(tenant_id="tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1",
                           season_start=date(2026, 10, 20), crop="TRZAX", kind="yield", model="aquacrop",
                           model_version="v1", as_of=date(2027, 5, 1), payload={"estimates": [WL, GC]}, inputs={})
    obs = {"harvest_date": "2027-07-05", "yield_t_ha": 5.0}
    rows = ps.score_rows([rec], obs)
    assert rows[0]["as_of"] == "2027-05-01" and rows[0]["lead_days"] == 65 and len(rows[0]["estimates"]) == 2
    assert ps.score_rows([rec], None)[0]["lead_days"] is None
    bare = PredictionRecord(tenant_id="tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1",
                            season_start=date(2026, 10, 20), crop="TRZAX", kind="yield", model="aquacrop",
                            model_version="v1", as_of=date(2027, 5, 1), payload={}, inputs={})
    assert ps.score_rows([bare], obs)[0]["estimates"] == []
