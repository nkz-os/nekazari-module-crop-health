"""actionable_jobs: every task of a parcel, with next_job still its first one."""
from datetime import date

from app.services.worklist import actionable_jobs, job_when, next_job

TODAY = date(2026, 11, 2)


def _args(**kw):
    base = dict(assessment=None, timeline=None, agro=None, alerts=[], forecast=None, today=TODAY)
    base.update(kw)
    return base


def _active():
    return {"current": {"species": "TRZDU", "start": {"date": "2026-03-01", "provenance": "actual"}}}


def test_actionable_jobs_returns_treat_and_irrigate():
    kw = _args(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"},
               alerts=[{"id": "urn:ngsi-ld:Alert:a1", "disease": "roya", "risk_level": "HIGH"}])
    jobs = actionable_jobs(**kw)
    assert [j["kind"] for j in jobs] == ["treat", "irrigate"]
    assert jobs[0]["detail"]["alertId"] == "urn:ngsi-ld:Alert:a1"


def test_next_job_unchanged():
    kw = _args(assessment={"recommendedAction": "IRRIGATE_IMMEDIATE"},
               alerts=[{"id": "a1", "disease": "roya", "risk_level": "HIGH"}])
    assert next_job(**kw) == {"kind": "treat", "when": "today", "detail": {"disease": "roya"}}
    assert next_job(**_args(assessment={"recommendedAction": "IRRIGATE_SCHEDULED"})) == \
        {"kind": "irrigate", "when": None, "detail": {"scheduled": True}}
    assert next_job(**_args(timeline=_active()))["kind"] == "pending_assessment"
    assert next_job(**_args(timeline=_active(), assessment={"recommendedAction": "NONE"}))["kind"] == "none_until"
    assert next_job(**_args()) is None


def test_when_mapping():
    assert job_when({"when": "today", "detail": {}}) == {"type": "today", "date": None}
    assert job_when({"when": None, "detail": {"scheduled": True}}) == {"type": "this_week", "date": None}
    assert job_when({"when": "2026-11-14", "detail": {}}) == {"type": "date", "date": "2026-11-14"}
    assert job_when({"when": None, "detail": {}}) == {"type": "undated", "date": None}


def test_pending_and_none_until_not_tasks():
    assert actionable_jobs(**_args(timeline=_active())) == []
    assert actionable_jobs(**_args(timeline=_active(), assessment={"recommendedAction": "NONE"})) == []
