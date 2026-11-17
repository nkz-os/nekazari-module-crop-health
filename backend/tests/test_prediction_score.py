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
    assert ps.pick_cycle(cycles, date(2026, 10, 20)) == (cycles[2], "exact")
    assert ps.pick_cycle(cycles, date(2026, 10, 25)) == (cycles[2], "by_date")
    assert ps.pick_cycle(cycles, date(2024, 1, 1)) == (None, None)
    assert ps.pick_cycle([_cycle(None)], date(2026, 10, 20)) == (None, None)


def test_pick_cycle_never_takes_the_previous_season_or_a_pending_cycle():
    # Last season's cycle was never closed (no end date) and carries a harvest: it must not be
    # scored against this season's predictions, whose sowing date was corrected by a few days.
    last = _cycle("2025-10-20", None, 30000.0)
    this = _cycle("2026-10-20")
    assert ps.pick_cycle([last, this], date(2026, 10, 25), "TRZAX") == (this, "by_date")
    assert ps.pick_cycle([last], date(2026, 10, 25), "TRZAX") == (None, None)
    assert ps.pick_cycle([_cycle("2026-09-05")], date(2026, 10, 20)) == (_cycle("2026-09-05"), "by_date")   # 45 days
    assert ps.pick_cycle([_cycle("2026-09-04")], date(2026, 10, 20)) == (None, None)                         # 46 days
    pending = dict(_cycle("2026-10-20"), pending=True)
    assert ps.pick_cycle([pending], date(2026, 10, 20)) == (None, None)
    near, nearer = _cycle("2026-10-01"), _cycle("2026-10-28")
    assert ps.pick_cycle([near, nearer], date(2026, 10, 25)) == (nearer, "by_date")


def test_observed_harvest_reasons_and_value():
    done = _cycle("2026-10-20", "2027-07-05", 40000.0)
    assert ps.observed_harvest(done, {"area": 8.0}) == ({
        "harvest_date": "2027-07-05", "weight_kg": 40000.0, "area_ha": 8.0, "yield_t_ha": 5.0,
        "basis": "as_delivered", "completeness": "unknown",
        "assumptions": ["weight_in_kg", "area_in_ha", "whole_parcel_harvested"]}, None)
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
    # same sign as error_t_ha (prediction minus observed): negative when the harvest beat the range
    assert ps.score_estimate(GC, 7.5)["distance_to_range_t_ha"] == -0.71
    assert ps.score_estimate(GC, 0.5)["distance_to_range_t_ha"] == 0.55
    both = dict(GC, percentiles={"p10": 2.0, "p50": 4.0, "p90": 6.0})
    over = ps.score_estimate(both, 7.5)
    assert over["error_t_ha"] == -3.5 and over["distance_to_range_t_ha"] == -0.71


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


def test_pick_cycle_only_matches_the_predicted_species():
    cover = dict(_cycle("2026-10-20"), species="VICSA")
    wheat = _cycle("2026-10-20")
    unnamed = dict(_cycle("2026-10-20"), species=None)
    assert ps.pick_cycle([cover, wheat], date(2026, 10, 20), "TRZAX") == (wheat, "exact")
    assert ps.pick_cycle([cover], date(2026, 10, 20), "TRZAX") == (None, None)
    assert ps.pick_cycle([unnamed], date(2026, 10, 20), "TRZAX") == (unnamed, "exact")
    grove = dict(_cycle("2015-03-01", lifecycle="perennial"), species="OLVEU")
    assert ps.pick_cycle([grove, wheat], date(2026, 10, 25), "TRZAX") == (wheat, "by_date")


def test_observed_harvest_states_its_assumptions():
    done = _cycle("2026-10-20", "2027-07-05", 40000.0)
    observed, _ = ps.observed_harvest(done, {"area": 8.0})
    assert observed["assumptions"] == ["weight_in_kg", "area_in_ha", "whole_parcel_harvested"]


def test_rows_logged_after_the_harvest_have_a_negative_lead():
    rec = PredictionRecord(tenant_id="tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1",
                           season_start=date(2026, 10, 20), crop="TRZAX", kind="yield", model="aquacrop",
                           model_version="v1", as_of=date(2027, 7, 10), payload={"estimates": [WL]}, inputs={})
    assert ps.score_rows([rec], {"harvest_date": "2027-07-05", "yield_t_ha": 5.0})[0]["lead_days"] == -5
