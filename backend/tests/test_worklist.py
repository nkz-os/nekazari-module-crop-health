from datetime import date, datetime, timedelta, timezone

from nkz_platform_sdk.crop_cycles import resolve_crop_cycles

from app.services.worklist import crop_status, freshness, next_job, planned_cycle, rank, surprise

TODAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _job(**kw):
    base = dict(assessment=None, timeline=None, agro=None, alerts=[], forecast=None, today=TODAY)
    base.update(kw)
    return next_job(**base)


def _active():
    return {"current": {"species": "TRZDU", "start": {"date": "2026-03-01", "provenance": "actual"}}}


def test_treat_wins_over_irrigate():
    job = _job(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"},
               alerts=[{"id": "a1", "disease": "roya", "risk_level": "HIGH"}])
    assert job["kind"] == "treat" and job["detail"]["disease"] == "roya"


def test_critical_and_lowercase_high_count():
    assert _job(alerts=[{"id": "a", "disease": "x", "risk_level": "critical"}])["kind"] == "treat"
    assert _job(alerts=[{"id": "a", "disease": "x", "risk_level": "high"}])["kind"] == "treat"


def test_low_or_missing_severity_is_not_a_job():
    assert _job(alerts=[{"id": "a", "risk_level": "low"}, {"id": "b"}]) is None


def test_irrigate_from_assessment():
    job = _job(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"})
    assert job["kind"] == "irrigate" and job["when"] == "today"


def test_sow_uses_pending_cycle_and_workability():
    tl = {"current": None, "pending": {"species": "TRZDU", "start": {"date": "2026-11-10", "provenance": "planned"}}}
    job = _job(timeline=tl, agro={"semaphores": {"workability": "optimal"}})
    assert (job["kind"], job["when"], job["detail"]["workability"]) == ("sow", "2026-11-10", "optimal")
    assert job["detail"]["crop"] == "TRZDU" and job["detail"]["species"] == "TRZDU"


def test_sow_crop_uses_name_when_present():
    tl = {"current": None, "pending": {"species": "TRZDU", "names": {"es": "Trigo duro"},
                                       "start": {"date": "2026-11-10", "provenance": "planned"}}}
    assert _job(timeline=tl)["detail"]["crop"] == "Trigo duro"


def test_harvest_from_forecast():
    fc = {"status": "done", "season": {"harvest_date": "2027-07-01"}}
    job = _job(timeline=_active(), assessment={"recommendedAction": "NONE"}, forecast=fc)
    assert (job["kind"], job["when"], job["detail"]) == ("harvest", "2027-07-01", {"date": "2027-07-01"})


def test_unavailable_forecast_is_not_harvest():
    fc = {"status": "unavailable", "season": None}
    job = _job(timeline=_active(), assessment={}, forecast=fc)
    assert job["kind"] != "harvest"


def test_pending_assessment():
    assert _job(timeline=_active())["kind"] == "pending_assessment"


def test_none_until_with_and_without_date():
    job = _job(timeline=_active(), assessment={"recommendedAction": "NONE"})
    assert job["kind"] == "none_until" and job["when"] is None and job["detail"] == {}


def test_planned_current_cycle_is_not_active():
    assert crop_status({"current": {"start": {"date": "2026-11-01", "provenance": "planned"}}}) == "none"
    assert crop_status({"current": {"start": {"provenance": "actual"}}}) == "none"
    assert crop_status(None) == "none"
    assert crop_status({"current": {"start": {"date": "2026-03-01", "provenance": "declared"}}}) == "active"
    assert crop_status(_active()) == "active"


def test_freshness_thresholds():
    ago = lambda **kw: (NOW - timedelta(**kw)).isoformat()
    assert freshness(ago(hours=47), NOW) == "fresh"
    assert freshness(ago(hours=48), NOW) == "fresh"
    assert freshness(ago(hours=49), NOW) == "aging"
    assert freshness(ago(days=7), NOW) == "aging"
    assert freshness(ago(days=8), NOW) == "stale"
    assert freshness(None, NOW) == "none"
    assert freshness("2026-10-26T10:00:00Z", NOW) == "fresh"
    assert freshness("2026-10-26T10:00:00", NOW) == "fresh"


def test_water_drop_surprise_from_history():
    hist = [{"cwsi": 0.2}, {"cwsi": 0.2}, {"cwsi": 0.25}, {"cwsi": 0.5}]
    assert surprise(assessment={}, history=hist, alerts=[])["code"] == "water_drop"


def test_water_drop_from_balance_and_none_values():
    hist = [{"balance": 30}, {"balance": 30}, {"balance": 30, "cwsi": None}, {"balance": 15}]
    assert surprise(assessment={}, history=hist, alerts=[])["code"] == "water_drop"
    calm = [{"balance": 30}, {"balance": 30}, {"balance": 30}, {"balance": 25}]
    assert surprise(assessment={}, history=calm, alerts=[]) is None
    assert surprise(assessment={}, history=[{"cwsi": 0.9}], alerts=[]) is None


def test_surprise_vigor_phenology_alert_precedence():
    assert surprise(assessment={"vigorCondition": "below_expected", "phenologyDeviation": "late"},
                    history=[], alerts=[])["code"] == "vigor_below_expected"
    assert surprise(assessment={"phenologyDeviation": "late"}, history=[], alerts=[])["code"] == "phenology_deviation"
    alerts = [{"id": "n1", "risk_level": "HIGH", "disease": "roya"}]
    assert surprise(assessment={}, history=[], alerts=alerts, previous_alert_ids={"n0"})["code"] == "new_high_alert"
    assert surprise(assessment={}, history=[], alerts=alerts, previous_alert_ids={"n1"}) is None
    assert surprise(assessment={}, history=[], alerts=alerts) is None
    assert surprise(assessment=None, history=[], alerts=[]) is None


def _row(name, **kw):
    base = {"name": name, "surprise": None, "nextJob": None, "cropStatus": "active",
            "hasData": True, "overallSeverity": "LOW"}
    base.update(kw)
    return base


def test_rank_orders_surprise_then_today_then_future():
    rows = [_row("b", nextJob={"when": "2026-11-10"}),
            _row("a", surprise={"code": "x"}),
            _row("c", nextJob={"when": "today"})]
    assert [r["name"] for r in sorted(rows, key=rank)] == ["a", "c", "b"]


def test_rank_full_group_order_severity_and_name():
    rows = [_row("nodata", hasData=False),
            _row("nocrop", cropStatus="none"),
            _row("calm"),
            _row("future", nextJob={"when": "2026-11-10"}),
            _row("today", nextJob={"when": "today"}),
            _row("surp", surprise={"code": "x"})]
    assert [r["name"] for r in sorted(rows, key=rank)] == ["surp", "today", "future", "calm", "nocrop", "nodata"]
    sev = [_row("z", overallSeverity="CRITICAL"), _row("y", overallSeverity="HIGH"),
           _row("b", overallSeverity="MEDIUM"), _row("a", overallSeverity="LOW"), _row("A", overallSeverity="LOW")]
    assert [r["name"] for r in sorted(sev, key=rank)] == ["z", "y", "b", "A", "a"]


def test_rank_reads_parcel_name():
    rows = [{"parcelName": "b", "cropStatus": "active", "hasData": True},
            {"parcelName": "a", "cropStatus": "active", "hasData": True}]
    assert [r["parcelName"] for r in sorted(rows, key=rank)] == ["a", "b"]


def test_sow_overdue_is_today_future_keeps_date():
    def tl(d):
        return {"current": None, "pending": {"species": "TRZDU", "start": {"date": d, "provenance": "planned"}}}
    assert _job(timeline=tl("2026-10-25"))["when"] == "today"
    assert _job(timeline=tl("2026-10-26"))["when"] == "today"
    assert _job(timeline=tl("2026-10-27"))["when"] == "2026-10-27"


def test_harvest_overdue_is_today_future_keeps_date():
    def job(d):
        return _job(timeline=_active(), assessment={}, forecast={"status": "done", "season": {"harvest_date": d}})
    assert job("2026-10-01")["when"] == "today"
    assert job("2026-12-01")["when"] == "2026-12-01"


def test_sow_without_date_has_no_when():
    job = _job(timeline={"current": None, "pending": {"species": "TRZDU"}})
    assert job["kind"] == "sow" and job["when"] is None


def test_none_until_with_pending_date():
    tl = _active()
    tl["pending"] = {"start": {"date": "2026-12-01", "provenance": "planned"}}
    job = _job(timeline=tl, assessment={})
    assert (job["kind"], job["when"], job["detail"]) == ("none_until", "2026-12-01", {"date": "2026-12-01"})


def test_cropless_dated_pending_without_species_is_none_until():
    tl = {"current": None, "pending": {"start": {"date": "2026-12-01", "provenance": "planned"}}}
    job = _job(timeline=tl)
    assert (job["kind"], job["when"]) == ("none_until", "2026-12-01")


def test_irrigate_beats_sow_and_sow_beats_harvest():
    tl = {"current": None, "pending": {"species": "TRZDU", "start": {"date": "2026-11-10", "provenance": "planned"}}}
    fc = {"status": "done", "season": {"harvest_date": "2026-12-01"}}
    assert _job(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"}, timeline=tl)["kind"] == "irrigate"
    assert _job(timeline=tl, forecast=fc)["kind"] == "sow"


def test_lang_selects_name():
    tl = {"current": None, "pending": {"species": "TRZDU", "names": {"es": "Trigo", "en": "Durum wheat"},
                                       "start": {"date": "2026-11-10", "provenance": "planned"}}}
    assert _job(timeline=tl, lang="en")["detail"]["crop"] == "Durum wheat"
    assert _job(timeline=tl, lang="fr")["detail"]["crop"] == "TRZDU"


def test_new_high_alert_with_empty_previous_set_fires():
    alerts = [{"id": "n1", "risk_level": "HIGH", "disease": "roya"}]
    assert surprise(assessment={}, history=[], alerts=alerts, previous_alert_ids=set())["code"] == "new_high_alert"


def test_rank_pending_assessment_is_no_data_group():
    rows = [_row("pend", nextJob={"kind": "pending_assessment", "when": None}),
            _row("nocrop", cropStatus="none"),
            _row("calm"),
            _row("future", nextJob={"kind": "sow", "when": "2026-11-10"})]
    assert [r["name"] for r in sorted(rows, key=rank)] == ["future", "calm", "nocrop", "pend"]


# ---- timelines built by the real SDK resolver (resolve_crop_cycles(...).to_dict()) ----
PID = "urn:ngsi-ld:AgriParcel:p1"


def _crop(cid, **kw):
    return {"id": f"urn:ngsi-ld:AgriCrop:{cid}", "hasAgriParcel": PID, "species": "TRZAX",
            "cropRole": "main_crop", **kw}


def _sdk(*crops, at=TODAY):
    return resolve_crop_cycles(PID, list(crops), [], at).to_dict()


def test_sdk_future_plan_is_sow_with_iso_date():
    tl = _sdk(_crop("a", sowingWindowStart="2026-11-10"))
    assert tl["pending"] is None and tl["next"]["start"]["provenance"] == "planned"
    job = _job(timeline=tl)
    assert (job["kind"], job["when"]) == ("sow", "2026-11-10")


def test_sdk_overdue_plan_is_sow_today():
    tl = _sdk(_crop("a", sowingWindowStart="2026-10-20"))
    assert tl["pending"] is not None
    assert (_job(timeline=tl)["kind"], _job(timeline=tl)["when"]) == ("sow", "today")


def test_sdk_overdue_plan_beats_future_plan():
    tl = _sdk(_crop("a", sowingWindowStart="2026-10-20", species="HORVU"),
              _crop("b", sowingWindowStart="2026-12-01"))
    job = _job(timeline=tl)
    assert (job["kind"], job["when"], job["detail"]["species"]) == ("sow", "today", "HORVU")
    assert planned_cycle(tl)["crop_id"].endswith(":a")


def test_sdk_undated_plan_is_sow_without_when():
    tl = _sdk(_crop("a"))
    assert tl["pending"] is None and tl["next"] is None
    job = _job(timeline=tl)
    assert (job["kind"], job["when"]) == ("sow", None)


def test_sdk_active_crop_with_next_plan_is_none_until_next_date():
    tl = _sdk(_crop("a", plantingDate="2026-03-01", plantingDateSource="manual", species="HORVU"),
              _crop("b", sowingWindowStart="2027-03-15"))
    assert crop_status(tl) == "active"
    job = _job(timeline=tl, assessment={"recommendedAction": "NO_ACTION"})
    assert (job["kind"], job["when"]) == ("none_until", "2027-03-15")


def test_sdk_declared_sowing_is_active():
    tl = _sdk(_crop("a", plantingDate="2026-03-01", plantingDateSource="manual"))
    assert tl["current"]["start"]["provenance"] == "declared"
    assert crop_status(tl) == "active"


def test_planned_cycle_ignores_closed_undated_and_non_main():
    tl = {"pending": None, "next": None, "cycles": [
        {"role": "cover_crop", "status": "planned", "start": {"date": None, "provenance": None}},
        {"role": "main_crop", "status": "harvested", "start": {"date": None, "provenance": None}},
    ]}
    assert planned_cycle(tl) is None
    assert planned_cycle(None) is None


def test_harvest_before_current_sowing_is_ignored():
    fc = {"status": "done", "season": {"harvest_date": "2026-01-15"}}
    job = _job(timeline=_active(), assessment={}, forecast=fc)
    assert job["kind"] != "harvest"


def test_scheduled_irrigation_is_future_work():
    job = _job(assessment={"recommendedAction": "IRRIGATE_SCHEDULED"})
    assert (job["kind"], job["when"], job["detail"]) == ("irrigate", None, {"scheduled": True})
    assert _job(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"})["when"] == "today"
    row = _row("s", nextJob=job)
    assert rank(row)[0] == 2


def test_anomalous_senescence_is_a_vigor_surprise():
    assert surprise(assessment={"vigorCondition": "anomalous_senescence"}, history=[], alerts=[])["code"] \
        == "vigor_below_expected"
    assert surprise(assessment={"vigorCondition": "stressed"}, history=[], alerts=[]) is None


def test_sdk_declared_future_sowing_is_sow_with_that_date():
    tl = _sdk(_crop("a", plantingDate="2026-11-20", plantingDateSource="manual", species="HORVU"))
    assert tl["next"]["start"]["provenance"] == "declared"
    assert planned_cycle(tl, TODAY)["species"] == "HORVU"
    job = _job(timeline=tl)
    assert (job["kind"], job["when"], job["detail"]["species"]) == ("sow", "2026-11-20", "HORVU")


def test_declared_next_in_the_past_is_not_planned():
    tl = {"pending": None, "cycles": [], "next": {"species": "X", "start": {"date": "2026-10-01", "provenance": "declared"}}}
    assert planned_cycle(tl, TODAY) is None
