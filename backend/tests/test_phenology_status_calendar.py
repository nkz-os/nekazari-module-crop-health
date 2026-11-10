"""phenology-status: additive cereal-calendar fields, observed-stage comparison, unchanged for other crops."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.engines import phenology_milestones as pm
from app.schemas import StageTable

STAGES = {"emergence": (0.0, 150.0), "vegetative": (150.0, 1450.0), "flowering": (1450.0, 1686.4),
          "grain_filling": (1686.4, 2809.1), "maturity": (2809.1, 2809.1)}
BBCH = {"emergence": (0, 9), "vegetative": (10, 49), "flowering": (51, 69), "grain_filling": (71, 87),
        "maturity": (89, 89)}
MODEL = {"id": "aquacrop_calendar", "cultivar": "WheatGDD", "version": "3.1.0"}
CAL = {"status": "calibrated", "version": "2026-10-13"}
VAL = {"status": "measured", "version": "2026-11-10"}
TABLE = StageTable(stages=STAGES, base_temp=0.0, upper_cutoff=26.0, gdd_method="aquacrop_m3",
                   stage_bbch=BBCH, model=MODEL, calibration=CAL, validation=VAL,
                   sources=[{"short": "s", "detail": "d"}], origin="sowing")
MILESTONES = {
    "emergence": {"gdd": 150.0, "status": "reached", "date": "2026-11-17"},
    "flowering_start": {"gdd": 1450.0, "status": "projected", "n_members": 15, "date_p10": "2027-04-08",
                        "date_p50": "2027-04-15", "date_p90": "2027-04-24"},
    "senescence_start": {"gdd": 1686.4, "status": "unavailable", "reason": "weather_unavailable"},
    "maturity": {"gdd": 2809.1, "status": "projected", "date_p50": "2027-06-20"},
}
SOWING = date(2026, 11, 1)


def test_milestone_date_uses_date_when_reached_and_p50_when_projected():
    assert pm.milestone_date(MILESTONES["emergence"]) == date(2026, 11, 17)
    assert pm.milestone_date(MILESTONES["flowering_start"]) == date(2027, 4, 15)
    assert pm.milestone_date(MILESTONES["senescence_start"]) is None
    assert pm.milestone_date(None) is None
    assert pm.milestone_date({"status": "reached"}) is None


@pytest.mark.parametrize("code,stage", [("05", "emergence"), ("31", "vegetative"), ("65", "flowering"),
                                        ("50", None), ("75", "grain_filling"), ("89", "maturity"), ("99", None)])
def test_stage_for_bbch(code, stage):
    assert pm.stage_for_bbch(code, TABLE) == stage


@pytest.mark.parametrize("code,ms", [("09", "emergence"), ("10", "emergence"), ("51", "flowering_start"),
                                     ("59", "flowering_start"), ("87", "maturity"), ("92", "maturity"),
                                     ("31", None), ("11", None), ("65", None), ("05", None)])
def test_milestone_for_bbch(code, ms):
    assert pm.milestone_for_bbch(code) == ms


@pytest.mark.parametrize("day,stage", [
    (date(2026, 10, 30), None),                # before sowing
    (date(2026, 11, 5), "emergence"),
    (date(2026, 12, 1), "vegetative"),
    (date(2027, 4, 20), None),                 # flowering started, grain filling start unknown: cannot say
    (date(2027, 6, 21), "maturity"),
])
def test_model_stage_on_date(day, stage):
    assert pm.model_stage_on_date(day, TABLE, MILESTONES, SOWING) == stage


def test_model_stage_between_known_starts_is_known():
    assert pm.model_stage_on_date(date(2027, 4, 14), TABLE, MILESTONES, SOWING) == "vegetative"


def test_model_stage_none_without_milestones():
    assert pm.model_stage_on_date(date(2026, 12, 1), TABLE, {}, SOWING) is None
    assert pm.model_stage_on_date(date(2026, 12, 1), TABLE, MILESTONES, None) == "vegetative"


def test_observation_rows_delta_is_model_minus_observed():
    rows = pm.observation_rows(
        [{"date": "2026-11-20", "bbch": "10"}, {"date": "2027-04-10", "bbch": "51"},
         {"date": "2027-03-01", "bbch": "31"}, {"date": "2027-06-30", "bbch": "89"}],
        TABLE, MILESTONES, SOWING)
    by = {r["bbch"]: r for r in rows}
    assert by["10"]["milestone"] == "emergence" and by["10"]["deltaDays"] == -3  # 11-17 minus 11-20
    assert by["10"]["stage"] == "vegetative" and by["10"]["modelStageOnDate"] == "vegetative"
    assert by["51"]["milestone"] == "flowering_start" and by["51"]["deltaDays"] == 5
    assert by["31"]["milestone"] is None and by["31"]["deltaDays"] is None
    assert by["89"]["milestone"] == "maturity" and by["89"]["deltaDays"] == -10
    assert by["89"]["stage"] == "maturity"


def test_delta_null_when_model_date_missing():
    ms = {**MILESTONES, "emergence": {"gdd": 150.0, "status": "unavailable", "reason": "x"}}
    row = pm.observation_rows([{"date": "2026-11-20", "bbch": "09"}], TABLE, ms, SOWING)[0]
    assert row["milestone"] == "emergence" and row["deltaDays"] is None
    row = pm.observation_rows([{"date": "2026-11-20", "bbch": "09"}], TABLE, None, SOWING)[0]
    assert row["deltaDays"] is None and row["modelStageOnDate"] is None


RECORD = {"status": "done", "season": {"sowing": {"date": "2026-11-01"}},
          "phenology": {"milestones": MILESTONES, "notes": ["no_stress_delay"], "basis": "thermal_time"}}


def _base_status():
    return {"parcelId": "p", "seasonStart": "2026-11-01", "currentStage": "vegetative",
            "stages": [{"stage": "emergence", "gddMin": 0.0, "gddMax": 150.0},
                       {"stage": "vegetative", "gddMin": 150.0, "gddMax": 1450.0}]}


def test_extend_status_adds_fields_only():
    base = _base_status()
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in base.items()}
    out = pm.extend_status(_base_status(), TABLE, RECORD, [{"date": "2026-11-20", "bbch": "10"}])
    for k in ("parcelId", "seasonStart", "currentStage"):
        assert out[k] == before[k]
    assert out["model"] == MODEL and out["calibration"] == CAL and out["validation"] == VAL
    assert out["sources"] == [{"short": "s", "detail": "d"}]
    assert out["experimental"] is True and out["basis"] == "thermal_time" and out["notes"] == ["no_stress_delay"]
    assert out["milestones"] == MILESTONES
    assert out["stages"][0] == {**before["stages"][0], "bbchFrom": 0, "bbchTo": 9}
    assert out["observations"][0]["milestone"] == "emergence"


def test_extend_status_leaves_other_crops_alone():
    base = _base_status()
    out = pm.extend_status(_base_status(), StageTable(stages={"emergence": (0.0, 90.0)}), None, [])
    assert out == base


# ── endpoint ───────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        c = TestClient(app)
        c.headers.update({"X-Tenant-ID": "tenant-a", "X-User-ID": "test-user"})
        return c


def _patch(monkeypatch, table, record=None, observed=None, season_start="2026-11-01"):
    from app.api import phenology

    async def _latest(parcel_id, tenant_id):
        return {"gddAccumulated": 300.0, "phenologyStage": "vegetative", "species": "wheat",
                "seasonStart": season_start}

    async def _table(species, parcel_id, tenant_id):
        return table

    async def _record(tenant_id, parcel_id):
        return record

    async def _observed(tenant_id, parcel_id, since):
        return observed or []

    monkeypatch.setattr(phenology, "_read_latest_assessment", _latest)
    monkeypatch.setattr(phenology.parcel_site, "get_parcel_stage_table", _table)
    monkeypatch.setattr(phenology, "_load_dates_record", _record)
    monkeypatch.setattr(phenology.observed_stage, "fetch_observed_stages", _observed)


URL = "/api/crop-health/parcels/urn:ngsi-ld:AgriParcel:p1/phenology-status"


def test_endpoint_cereal_example(client, monkeypatch):
    _patch(monkeypatch, TABLE, RECORD, [{"date": "2026-11-20", "bbch": "10"}])
    body = client.get(URL).json()
    assert body["currentStage"] == "vegetative" and body["gdd"] == {"accumulated": 300.0}
    assert body["model"]["id"] == "aquacrop_calendar" and body["experimental"] is True
    assert body["milestones"]["emergence"]["date"] == "2026-11-17"
    assert body["stages"][0]["bbchFrom"] == 0
    assert body["observations"] == [{"date": "2026-11-20", "bbch": "10", "stage": "vegetative",
                                     "modelStageOnDate": "vegetative", "milestone": "emergence",
                                     "deltaDays": -3}]


def test_endpoint_non_cereal_is_byte_identical_to_before(client, monkeypatch):
    plain = StageTable(stages={"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0)})
    _patch(monkeypatch, plain, RECORD, [{"date": "2026-11-20", "bbch": "10"}])
    from app.api import phenology

    async def _boom(*a, **k):
        raise AssertionError("no notebook read for other crops")

    monkeypatch.setattr(phenology.observed_stage, "fetch_observed_stages", _boom)
    body = client.get(URL).json()
    expected = phenology._build_status_from_dict(
        {"gddAccumulated": 300.0, "phenologyStage": "vegetative", "species": "wheat", "seasonStart": "2026-11-01"},
        plain)
    assert body == expected
    for k in ("model", "milestones", "observations", "experimental", "calibration", "validation", "sources"):
        assert k not in body


def test_endpoint_record_of_another_cycle_is_ignored(client, monkeypatch):
    _patch(monkeypatch, TABLE, RECORD, [], season_start="2027-10-20")
    body = client.get(URL).json()
    assert "milestones" not in body and body["observations"] == []


def test_endpoint_survives_calendar_failure(client, monkeypatch):
    _patch(monkeypatch, TABLE, RECORD)
    from app.api import phenology

    async def _boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(phenology.observed_stage, "fetch_observed_stages", _boom)
    body = client.get(URL).json()
    assert body["currentStage"] == "vegetative" and "milestones" not in body


def _fixed_rate_status():
    """A status as the base builder leaves it: stage dates projected at a fixed daily rate."""
    return {"seasonStart": "2026-11-01", "stages": [
        {"stage": "emergence", "gddMin": 0.0, "gddMax": 150.0, "reached": True, "current": False,
         "projectedDate": None, "projectedEnd": None},
        {"stage": "vegetative", "gddMin": 150.0, "gddMax": 1450.0, "reached": True, "current": True,
         "projectedDate": None, "projectedEnd": "2027-04-01"},
        {"stage": "flowering", "gddMin": 1450.0, "gddMax": 1686.4, "reached": False, "current": False,
         "projectedDate": "2027-04-01", "projectedEnd": None},
        {"stage": "grain_filling", "gddMin": 1686.4, "gddMax": 2809.1, "reached": False, "current": False,
         "projectedDate": "2027-05-01", "projectedEnd": None},
        {"stage": "maturity", "gddMin": 2809.1, "gddMax": 2809.1, "reached": False, "current": False,
         "projectedDate": "2027-09-01", "projectedEnd": None},
    ]}


def test_calendar_stage_dates_come_from_the_milestones_never_from_the_fixed_rate():
    record = {"season": {"sowing": {"date": "2026-11-01"}}, "phenology": {"milestones": MILESTONES}}
    out = pm.extend_status(_fixed_rate_status(), TABLE, record, [])
    by = {s["stage"]: s for s in out["stages"]}
    assert by["flowering"]["projectedDate"] == "2027-04-15"       # the milestone's median date
    assert by["vegetative"]["projectedEnd"] == "2027-04-15"       # the current stage ends where the next begins
    assert by["maturity"]["projectedDate"] == "2027-06-20"
    assert by["grain_filling"]["projectedDate"] is None           # no milestone dates it: no date at all
    assert by["emergence"]["projectedDate"] is None and by["emergence"]["projectedEnd"] is None


def test_calendar_stage_dates_are_blank_without_a_milestone_answer():
    out = pm.extend_status(_fixed_rate_status(), TABLE, None, [])
    assert all(s["projectedDate"] is None and s["projectedEnd"] is None for s in out["stages"])


def test_other_crops_keep_their_projected_stage_dates():
    plain = StageTable(stages={"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0)}, base_temp=10.0)
    status = {"stages": [{"stage": "vegetative", "gddMin": 90.0, "gddMax": 520.0, "reached": False, "current": False,
                          "projectedDate": "2027-04-01", "projectedEnd": None}]}
    out = pm.extend_status(status, plain, None, [])
    assert out["stages"][0]["projectedDate"] == "2027-04-01"
