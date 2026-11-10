"""Milestone dates: client, store rules, prediction-log row, failure isolation."""
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.schemas import StageTable
from app.services import parcel_site, phenology_dates, phenology_dates_client
from app.services import prediction_log as plog
from app.services.prediction_log import MemoryPredictionLog
from tests.test_yield_forecast_run import FakeState

URN = "urn:ngsi-ld:AgriParcel:p1"
BASE = "http://bioorch.test"
URL = f"{BASE}/api/graph/planning/parcels/urn%3Angsi-ld%3AAgriParcel%3Ap1/phenology"

VALIDATION = {"status": "measured", "version": "2026-11-10"}
CAL = {"status": "calibrated", "scheme": "es_province", "version": "2026-10-13"}
DONE = {
    "contract_version": "2.8", "provider_id": "aquacrop_calendar", "state": "done", "unavailable": [],
    "season": {"crop": "TRZAX", "sowing": {"date": "2026-11-01", "source": "crop_cycle", "provenance": "actual"},
               "regime": "rainfed", "as_of": "2026-11-09", "weather_source": "archive"},
    "phenology": {"gdd_method": "aquacrop_m3", "base_temp": 0.0, "upper_cutoff": 26.0, "origin": "sowing",
                  "basis": "thermal_time", "notes": ["no_stress_delay"], "validation": VALIDATION,
                  "model": {"id": "aquacrop_calendar", "cultivar": "WheatGDD", "version": "3.1.0"},
                  "calibration": CAL,
                  "milestones": {"emergence": {"gdd": 150.0, "status": "reached", "date": "2026-11-17"}}},
}
CAL_TABLE = StageTable(stages={"emergence": (0.0, 150.0)}, model={"id": "aquacrop_calendar"})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    s = phenology_dates_client.get_settings()
    monkeypatch.setattr(s, "bioorchestrator_url", BASE)
    monkeypatch.setattr(s, "internal_service_secret", "sec")


@pytest.fixture
def log(monkeypatch):
    m = MemoryPredictionLog()
    monkeypatch.setattr(plog, "get_prediction_log", lambda: m)
    return m


def _table(monkeypatch, table):
    monkeypatch.setattr(parcel_site, "get_parcel_stage_table", AsyncMock(return_value=table))


@pytest.mark.anyio
async def test_client_sends_signed_headers_and_returns_answer():
    with respx.mock as m:
        route = m.get(URL).respond(200, json=DONE)
        out = await phenology_dates_client.fetch_phenology_dates(URN, "tenant-a")
    assert out["state"] == "done"
    h = route.calls[0].request.headers
    assert h["X-Internal-Service-Secret"] == "sec" and h["X-Tenant-ID"] == "tenant-a"


@pytest.mark.anyio
@pytest.mark.parametrize("resp,state,code", [
    (httpx.Response(404), "unavailable", "404"),
    (httpx.Response(500), "failed", "500"),
    (httpx.Response(200, json={"contract_version": "3.0", "state": "done"}), "failed", "contract_mismatch"),
    (httpx.Response(200, text="nope"), "failed", "invalid_json"),
])
async def test_client_never_raises(resp, state, code):
    with respx.mock as m:
        m.get(URL).mock(return_value=resp)
        out = await phenology_dates_client.fetch_phenology_dates(URN, "tenant-a")
    assert out["state"] == state and out["unavailable"][0]["code"] == code


@pytest.mark.anyio
async def test_client_total_timeout(monkeypatch):
    """One total budget per call, not per phase: a peer that trickles bytes cannot hold the batch."""
    import asyncio

    monkeypatch.setattr(phenology_dates_client, "_TOTAL_TIMEOUT_S", 0.05)

    async def _slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=DONE)

    with respx.mock as m:
        m.get(URL).mock(side_effect=_slow)
        out = await phenology_dates_client.fetch_phenology_dates(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "timeout"


def test_client_total_timeout_default_is_15_seconds():
    assert phenology_dates_client._TOTAL_TIMEOUT_S == 15.0


@pytest.mark.anyio
async def test_refresh_reports_failed_outcome(monkeypatch):
    _table(monkeypatch, CAL_TABLE)
    failed = {"state": "failed", "unavailable": [{"reason": "request_failed", "code": "timeout"}]}
    with patch.object(phenology_dates, "fetch_phenology_dates", AsyncMock(return_value=failed)):
        assert await phenology_dates.refresh(FakeState(), "tenant-a", "p1", "wheat") == "failed"


@pytest.mark.anyio
async def test_client_transport_error():
    with respx.mock as m:
        m.get(URL).mock(side_effect=httpx.ConnectError("x"))
        out = await phenology_dates_client.fetch_phenology_dates(URN, "tenant-a")
    assert out["state"] == "failed"


@pytest.mark.anyio
async def test_done_is_stored_and_logged_once(monkeypatch, log):
    _table(monkeypatch, CAL_TABLE)
    st = FakeState()
    with patch.object(phenology_dates, "fetch_phenology_dates", AsyncMock(return_value=DONE)):
        assert await phenology_dates.refresh(st, "tenant-a", "p1", "wheat") == "written"
        await phenology_dates.refresh(st, "tenant-a", URN, "wheat")
    rec = st.data[f"phenology-dates:tenant-a:{URN}"]
    assert rec["status"] == "done" and rec["phenology"]["milestones"] == DONE["phenology"]["milestones"]
    rows = await log.list("tenant-a", URN)
    assert len(rows) == 1  # same key twice: idempotent
    r = rows[0]
    assert (r.kind, r.model, r.model_version, r.crop) == ("phenology", "aquacrop_calendar", "3.1.0+2026-10-13", "TRZAX")
    assert r.season_start == date(2026, 11, 1) and r.as_of == date(2026, 11, 9)
    assert r.payload == {"milestones": DONE["phenology"]["milestones"], "basis": "thermal_time",
                         "notes": ["no_stress_delay"]}
    assert r.inputs["gdd_method"] == "aquacrop_m3" and r.inputs["calibration"] == CAL
    assert r.inputs["validation_version"] == "2026-11-10" and r.inputs["regime"] == "rainfed"
    assert r.inputs["weather_source"] == "archive" and r.inputs["sowing"]["date"] == "2026-11-01"


@pytest.mark.anyio
async def test_not_a_calendar_table_makes_no_call(monkeypatch, log):
    _table(monkeypatch, StageTable())
    fetch = AsyncMock()
    with patch.object(phenology_dates, "fetch_phenology_dates", fetch):
        assert await phenology_dates.refresh(FakeState(), "tenant-a", "p1", "Zea mays") == "not_calendar"
    fetch.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("answer,outcome", [
    ({"state": "unavailable", "unavailable": [{"reason": "not_sown"}]}, "kept"),
    ({"state": "failed", "unavailable": [{"reason": "request_failed"}]}, "failed"),
])
async def test_not_done_keeps_previous_and_logs_nothing(monkeypatch, log, answer, outcome):
    _table(monkeypatch, CAL_TABLE)
    st = FakeState()
    st.data[f"phenology-dates:tenant-a:{URN}"] = {"status": "done", "old": True}
    with patch.object(phenology_dates, "fetch_phenology_dates", AsyncMock(return_value=answer)):
        assert await phenology_dates.refresh(st, "tenant-a", "p1", "wheat") == outcome
    assert st.data[f"phenology-dates:tenant-a:{URN}"] == {"status": "done", "old": True}
    assert await log.list("tenant-a", URN) == []


@pytest.mark.anyio
async def test_log_failure_does_not_stop_the_store(monkeypatch, caplog):
    _table(monkeypatch, CAL_TABLE)

    class _Broken:
        async def append(self, record):
            raise RuntimeError("db down")

    monkeypatch.setattr(plog, "get_prediction_log", lambda: _Broken())
    st = FakeState()
    with patch.object(phenology_dates, "fetch_phenology_dates", AsyncMock(return_value=DONE)):
        with caplog.at_level("ERROR"):
            assert await phenology_dates.refresh(st, "tenant-a", "p1", "wheat") == "written"
    assert f"phenology-dates:tenant-a:{URN}" in st.data
    assert "tenant=tenant-a" in caplog.text and "parcel=" in caplog.text


@pytest.mark.anyio
async def test_incomplete_answer_is_not_logged(monkeypatch, log):
    _table(monkeypatch, CAL_TABLE)
    bad = {**DONE, "season": {**DONE["season"], "as_of": None}}
    with patch.object(phenology_dates, "fetch_phenology_dates", AsyncMock(return_value=bad)):
        assert await phenology_dates.refresh(FakeState(), "tenant-a", "p1", "wheat") == "written"
    assert await log.list("tenant-a", URN) == []


@pytest.mark.anyio
async def test_refresh_never_raises(monkeypatch, caplog):
    monkeypatch.setattr(parcel_site, "get_parcel_stage_table", AsyncMock(side_effect=RuntimeError("boom")))
    with caplog.at_level("ERROR"):
        assert await phenology_dates.refresh(FakeState(), "tenant-a", "p1", "wheat") == "error"
    assert "tenant=tenant-a" in caplog.text
