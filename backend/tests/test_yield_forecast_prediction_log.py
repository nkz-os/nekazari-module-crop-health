"""compute_and_store appends one 'yield' row per answer with an estimate; never breaks the store path."""
import logging
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services import prediction_log as plog
from app.services import yield_forecast
from app.services.prediction_log import MemoryPredictionLog
from tests.test_yield_forecast_run import FakeState

URN = "urn:ngsi-ld:AgriParcel:p1"
EST = {"provider_id": "aquacrop", "provider_version": "0.9.1", "basis": "gap_corrected", "unit": "t/ha",
       "percentiles": {"p10": 4.0, "p50": 5.0, "p90": 6.0}, "n": 20, "n_kind": "years",
       "validation": {"status": "experimental", "scope": "s"}, "warnings": [], "attributions": []}
SEASON = {"status": "in_season", "as_of": "2026-05-01", "crop": "TRZAX", "regime": "rainfed",
          "sowing": {"date": "2026-03-01", "source": "crop_cycle", "provenance": "actual"},
          "sowing_method": "direct", "sowing_method_source": "default", "harvest_date": "2026-07-01",
          "n_years": 20, "weather_source": "archive", "computed_at": "2026-05-02T03:00:00Z",
          "provider_version": "0.9.1"}
DONE = {"contract_version": "2.1", "provider_id": "aquacrop", "state": "done", "estimates": [EST],
        "unavailable": [], "season": SEASON}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def log(monkeypatch):
    m = MemoryPredictionLog()
    monkeypatch.setattr(plog, "get_prediction_log", lambda: m)
    return m


async def _run(answer, st=None):
    st = st or FakeState()
    with patch.object(yield_forecast, "fetch_in_season", AsyncMock(return_value=answer)):
        return await yield_forecast.compute_and_store(st, "tenant-a", "p1"), st


@pytest.mark.anyio
async def test_done_appends_one_yield_row(log):
    out, st = await _run(DONE)
    assert out == "written"
    rows = await log.list("tenant-a", URN)
    assert len(rows) == 1
    r = rows[0]
    assert (r.kind, r.model, r.model_version, r.crop) == ("yield", "aquacrop", "0.9.1", "TRZAX")
    assert r.season_start == date(2026, 3, 1) and r.as_of == date(2026, 5, 1)
    assert r.payload["estimates"] == [EST] and r.payload["season_status"] == "in_season"
    assert r.payload["harvest_date"] == "2026-07-01"
    assert r.inputs["sowing"] == SEASON["sowing"] and r.inputs["regime"] == "rainfed"
    assert r.inputs["weather_source"] == "archive" and r.inputs["contract_version"] == "2.1"
    assert "soil" not in r.inputs


@pytest.mark.anyio
async def test_repeat_same_day_adds_nothing(log):
    await _run(DONE)
    await _run({**DONE, "estimates": [{**EST, "percentiles": {"p10": 1, "p50": 2, "p90": 3}}]})
    rows = await log.list("tenant-a", URN)
    assert len(rows) == 1 and rows[0].payload["estimates"][0]["percentiles"]["p50"] == 5.0


@pytest.mark.anyio
@pytest.mark.parametrize("answer", [
    {"state": "unavailable", "unavailable": [{"reason": "not_sown"}]},
    {"state": "failed", "unavailable": [{"reason": "request_failed", "code": "503"}]},
    {**DONE, "estimates": []},
])
async def test_no_estimate_no_row(log, answer):
    await _run(answer)
    assert await log.list("tenant-a", URN) == []


@pytest.mark.anyio
@pytest.mark.parametrize("mutate", [
    lambda s: {**s, "as_of": None},
    lambda s: {**s, "crop": ""},
    lambda s: {**s, "sowing": None},
    lambda s: {**s, "sowing": {"date": "garbage"}},
])
async def test_missing_key_field_skips_and_logs(log, caplog, mutate):
    with caplog.at_level(logging.WARNING):
        out, _ = await _run({**DONE, "season": mutate(SEASON)})
    assert out == "written" and await log.list("tenant-a", URN) == []
    assert "prediction_log skipped" in caplog.text and "tenant-a" in caplog.text


@pytest.mark.anyio
async def test_no_season_skips(log):
    out, _ = await _run({**DONE, "season": None})
    assert out == "written" and await log.list("tenant-a", URN) == []


@pytest.mark.anyio
async def test_append_failure_is_swallowed_and_logged(monkeypatch, caplog):
    class Boom:
        async def append(self, r):
            raise RuntimeError("db down")

    monkeypatch.setattr(plog, "get_prediction_log", lambda: Boom())
    with caplog.at_level(logging.ERROR):
        out, st = await _run(DONE)
    assert out == "written" and st.data[f"yield-forecast:tenant-a:{URN}"]["status"] == "done"
    assert "tenant-a" in caplog.text and "aquacrop" in caplog.text


@pytest.mark.anyio
async def test_log_off_does_not_change_outcome(monkeypatch):
    monkeypatch.setattr(plog, "get_prediction_log", lambda: None)
    out, st = await _run(DONE)
    assert out == "written"
