"""next_record: the D6 truth table (spec §4.2)."""
from datetime import datetime, timezone

import pytest

from app.services.yield_forecast import next_record, parcel_urn

NOW = datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)
SEASON = {"status": "in_season", "crop": "TRZAX", "regime": "rainfed", "sowing": {"date": "2026-10-01"}}
EST = [{"provider_id": "aquacrop", "basis": "gap_corrected"}, {"provider_id": "wofost", "basis": "water_limited"}]
DONE_PREV = {"status": "done", "estimates": EST, "season": SEASON, "computed_at": "2026-10-13T05:00:00+00:00"}


def _unav(reason, code=None):
    return {"state": "unavailable", "unavailable": [{"provider_id": "aquacrop", "reason": reason, "code": code}]}


def test_done_writes_all_providers_as_received():
    rec = next_record(None, {"state": "done", "estimates": EST, "season": SEASON, "unavailable": []}, NOW)
    assert rec["status"] == "done" and rec["estimates"] == EST and rec["season"] == SEASON
    assert rec["computed_at"] == rec["attempted_at"] == NOW.isoformat() and rec["last_error"] is None


def test_season_ended_keeps_previous_done():
    rec = next_record(DONE_PREV, _unav("season_ended"), NOW)
    assert rec["status"] == "season_ended" and rec["estimates"] == EST
    assert rec["computed_at"] == DONE_PREV["computed_at"] and rec["attempted_at"] == NOW.isoformat()


def test_season_ended_without_previous():
    rec = next_record(None, _unav("season_ended"), NOW)
    assert rec["status"] == "season_ended" and rec["estimates"] == []


def test_busy_leaves_store():
    assert next_record(DONE_PREV, _unav("busy"), NOW) is None


def test_other_reason_replaces():
    rec = next_record(DONE_PREV, _unav("not_sown"), NOW)
    assert rec == {"status": "unavailable", "reason": "not_sown", "code": None, "season": None,
                   "estimates": [], "computed_at": NOW.isoformat(), "attempted_at": NOW.isoformat(),
                   "last_error": None}


def test_failed_keeps_previous_with_error():
    rec = next_record(DONE_PREV, {"state": "failed", "unavailable": [{"reason": "engine_error", "code": "weather_unavailable"}]}, NOW)
    assert rec["status"] == "done" and rec["estimates"] == EST
    assert rec["last_error"] == {"reason": "engine_error", "code": "weather_unavailable", "at": NOW.isoformat()}


def test_failed_without_previous():
    rec = next_record(None, {"state": "failed", "unavailable": [{"reason": "request_failed", "code": "503"}]}, NOW)
    assert rec["status"] == "failed" and rec["reason"] == "request_failed" and rec["code"] == "503"


@pytest.mark.parametrize("state", ["queued", "running"])
def test_unsettled_leaves_store(state):
    assert next_record(DONE_PREV, {"state": state}, NOW) is None


def test_failed_without_reason_list():
    rec = next_record(None, {"state": "failed"}, NOW)
    assert rec["status"] == "failed" and rec["reason"] == "unknown"


@pytest.mark.parametrize("raw,urn", [
    ("d2e55461-eeb2-411d-b5f6-2f026e536914", "urn:ngsi-ld:AgriParcel:d2e55461-eeb2-411d-b5f6-2f026e536914"),
    ("urn:ngsi-ld:AgriParcel:x", "urn:ngsi-ld:AgriParcel:x"),
])
def test_parcel_urn(raw, urn):
    assert parcel_urn(raw) == urn
