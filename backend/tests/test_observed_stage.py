"""Scouting operations with an observed BBCH stage, read through the SDK broker client."""
from datetime import date

import pytest

from app.services import observed_stage

CAPTURE = {}


class _Orion:
    rows: list = []
    fail = False

    def __init__(self, tenant, **k):
        CAPTURE["tenant"] = tenant

    async def query_entities(self, **kw):
        CAPTURE.setdefault("calls", []).append(kw)
        if self.fail:
            raise RuntimeError("broker down")
        off = kw["offset"]
        return self.rows[off:off + kw["limit"]]

    async def close(self):
        return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CAPTURE.clear()
    _Orion.fail = False
    monkeypatch.setattr(observed_stage, "OrionClient", _Orion)


@pytest.mark.asyncio
async def test_three_spellings_and_query():
    _Orion.rows = [
        {"id": "a", "startedAt": "2026-12-01T08:00:00Z", "phenologicalStage": "13"},
        {"id": "b", "startedAt": "2027-02-10T08:00:00Z", "nkz:phenologicalStage": {"type": "Property", "value": "31"}},
        {"id": "c", "startedAt": "2027-03-10T23:30:00-02:00", "https://nkz-os.org/ns/phenologicalStage": "39"},
        {"id": "e", "startedAt": "2027-03-12T00:30:00+02:00", "phenologicalStage": "41"},
        {"id": "d", "startedAt": "2027-03-11T08:00:00Z"},
    ]
    out = await observed_stage.fetch_observed_stages("tenant-a", "p1", date(2026, 11, 1))
    assert out == [{"date": "2026-12-01", "bbch": "13"}, {"date": "2027-02-10", "bbch": "31"},
                   {"date": "2027-03-10", "bbch": "39"}, {"date": "2027-03-12", "bbch": "41"}]
    q = CAPTURE["calls"][0]
    assert q["type"] == "AgriParcelOperation" and q["options"] == "keyValues" and q["limit"] == 200
    assert 'operationType=="scouting"' in q["q"]
    assert 'hasAgriParcel=="urn:ngsi-ld:AgriParcel:p1"' in q["q"] and "refAgriParcel==" in q["q"]
    assert 'startedAt[@value]>="2026-10-31"' in q["q"]


@pytest.mark.asyncio
async def test_before_sowing_and_bad_values_skipped():
    _Orion.rows = [
        {"id": "a", "startedAt": "2026-10-30T08:00:00Z", "phenologicalStage": "13"},
        {"id": "a2", "startedAt": "2026-10-31T08:00:00Z", "phenologicalStage": "11"},
        {"id": "b", "startedAt": "2026-12-01T08:00:00Z", "phenologicalStage": "tillering"},
        {"id": "c", "startedAt": "garbage", "phenologicalStage": "13"},
        {"id": "d", "startedAt": "2026-12-02T08:00:00Z", "phenologicalStage": 5},
    ]
    out = await observed_stage.fetch_observed_stages("tenant-a", "urn:ngsi-ld:AgriParcel:p1", date(2026, 11, 1))
    assert out == [{"date": "2026-10-31", "bbch": "11"}, {"date": "2026-12-02", "bbch": "05"}]


@pytest.mark.asyncio
async def test_early_morning_note_with_positive_offset_keeps_its_written_day():
    _Orion.rows = [{"id": "a", "startedAt": "2026-11-01T01:30:00+02:00", "phenologicalStage": "05"}]
    out = await observed_stage.fetch_observed_stages("tenant-a", "p1", date(2026, 11, 1))
    assert out == [{"date": "2026-11-01", "bbch": "05"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ['p1" | type=="X', "p 1", "", "a" * 200, "p1\n"])
async def test_bad_parcel_id_builds_no_filter(caplog, bad):
    _Orion.rows = [{"id": "a", "startedAt": "2026-12-01T08:00:00Z", "phenologicalStage": "13"}]
    with caplog.at_level("WARNING"):
        assert await observed_stage.fetch_observed_stages("tenant-a", bad, date(2026, 11, 1)) == []
    assert "calls" not in CAPTURE and "rejected" in caplog.text


@pytest.mark.asyncio
async def test_malformed_stage_logs_at_debug_only(caplog):
    _Orion.rows = [{"id": "b", "startedAt": "2026-12-01T08:00:00Z", "phenologicalStage": "tillering"}]
    with caplog.at_level("WARNING"):
        await observed_stage.fetch_observed_stages("tenant-a", "p1", date(2026, 11, 1))
    assert caplog.records == []


@pytest.mark.asyncio
async def test_failure_gives_empty_list_and_warning(caplog):
    _Orion.fail = True
    with caplog.at_level("WARNING"):
        assert await observed_stage.fetch_observed_stages("tenant-a", "p1", date(2026, 11, 1)) == []
    assert "tenant=tenant-a" in caplog.text and "AgriParcel:p1" in caplog.text


@pytest.mark.asyncio
async def test_pages_until_short_page():
    _Orion.rows = [{"id": str(i), "startedAt": "2026-12-01T08:00:00Z", "phenologicalStage": "13"}
                   for i in range(250)]
    out = await observed_stage.fetch_observed_stages("tenant-a", "p1", date(2026, 11, 1))
    assert len(out) == 250 and len(CAPTURE["calls"]) == 2
