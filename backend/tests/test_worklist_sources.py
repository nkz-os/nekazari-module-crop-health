"""Work-list sources: every fetcher fails soft (None / [])."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.config import get_settings
from app.services import pipeline, worklist_sources as ws
from app.services.redis_state import StoreError

TENANT = "tenant-a"
SHORT = "p1"
URN = "urn:ngsi-ld:AgriParcel:p1"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(pipeline, "_hmac_secret", lambda: "test-secret")
    monkeypatch.setattr(ws, "_hmac_secret", lambda: "test-secret")


def _url():
    return f"{get_settings().weather_daily_url}/api/weather/parcel/{SHORT}/agro-status"


@pytest.mark.asyncio
@respx.mock
async def test_agro_status_ok_is_signed():
    route = respx.get(_url()).mock(return_value=httpx.Response(200, json={"a": 1}))
    assert await ws.fetch_agro_status(TENANT, SHORT) == {"a": 1}
    h = route.calls.last.request.headers
    assert h["x-auth-signature"] and h["x-tenant-id"] == TENANT


@pytest.mark.asyncio
@respx.mock
async def test_agro_status_401_none():
    respx.get(_url()).mock(return_value=httpx.Response(401))
    assert await ws.fetch_agro_status(TENANT, SHORT) is None


@pytest.mark.asyncio
@respx.mock
async def test_agro_status_timeout_none():
    respx.get(_url()).mock(side_effect=httpx.ReadTimeout("t"))
    assert await ws.fetch_agro_status(TENANT, SHORT) is None


@pytest.mark.asyncio
async def test_agro_status_no_secret_none(monkeypatch):
    monkeypatch.setattr(ws, "_hmac_secret", lambda: "")
    assert await ws.fetch_agro_status(TENANT, SHORT) is None


@pytest.mark.asyncio
async def test_timeline_ok_and_accepts_short_id():
    m = AsyncMock(return_value={"x": 1})
    with patch.object(ws, "fetch_crop_timeline", m):
        assert await ws.fetch_timeline(TENANT, SHORT) == {"x": 1}
    assert m.call_args.args[1] == URN


@pytest.mark.asyncio
async def test_timeline_error_none():
    with patch.object(ws, "fetch_crop_timeline", AsyncMock(side_effect=RuntimeError)):
        assert await ws.fetch_timeline(TENANT, URN) is None


class _State:
    def __init__(self, get_json):
        self.get_json = get_json


@pytest.mark.asyncio
async def test_forecast_reads_record_key():
    from app.services.yield_forecast import record_key
    st = _State(AsyncMock(return_value={"status": "ok"}))
    assert await ws.fetch_forecast(st, TENANT, SHORT) == {"status": "ok"}
    st.get_json.assert_awaited_once_with(record_key(TENANT, URN))


@pytest.mark.asyncio
async def test_forecast_absent_or_store_error_none():
    assert await ws.fetch_forecast(_State(AsyncMock(return_value=None)), TENANT, URN) is None
    assert await ws.fetch_forecast(_State(AsyncMock(side_effect=StoreError("x"))), TENANT, URN) is None


@pytest.mark.asyncio
async def test_history_delegates():
    with patch.object(ws, "_history_points", AsyncMock(return_value=[{"d": 1}])) as m:
        assert await ws.fetch_history("req", SHORT, days=3) == [{"d": 1}]
    m.assert_awaited_once_with("req", SHORT, 3)


@pytest.mark.asyncio
async def test_gather_maps_exceptions_and_skips_history():
    with patch.object(ws, "fetch_timeline", AsyncMock(side_effect=RuntimeError)), \
         patch.object(ws, "fetch_agro_status", AsyncMock(return_value={"a": 1})), \
         patch.object(ws, "fetch_forecast", AsyncMock(side_effect=ValueError)), \
         patch.object(ws, "fetch_history", AsyncMock(side_effect=KeyError)) as h:
        out = await ws.gather_parcel_inputs("req", object(), TENANT, SHORT, with_history=True)
        assert out == {"timeline": None, "agro": {"a": 1}, "forecast": None, "history": []}
        h.reset_mock()
        out = await ws.gather_parcel_inputs("req", object(), TENANT, SHORT, with_history=False)
        assert out["history"] == [] and not h.called


@pytest.mark.asyncio
async def test_alert_rows_carry_id_and_are_unfiltered():
    from app.api import assessments

    ents = [
        {"id": "urn:ngsi-ld:Alert:1", "category": "disease", "refEntity": "urn:ngsi-ld:AgriParcel:p1"},
        {"id": "urn:ngsi-ld:Alert:2", "category": "disease", "refEntity": "urn:ngsi-ld:AgriParcel:p2"},
        {"id": "urn:ngsi-ld:Alert:3", "category": "frost", "refEntity": "urn:ngsi-ld:AgriParcel:p1"},
    ]
    client = AsyncMock()
    client.query_entities.return_value = ents
    with patch.object(assessments, "OrionClient", return_value=client):
        rows = await assessments._active_alert_rows(TENANT)
    assert [(r["id"], r["parcelId"]) for r in rows] == [
        ("urn:ngsi-ld:Alert:1", "p1"), ("urn:ngsi-ld:Alert:2", "p2")]


@pytest.fixture(autouse=True)
def _fresh_agro_cache():
    ws._agro_cache.clear()
    yield
    ws._agro_cache.clear()


@respx.mock
async def test_agro_status_calls_are_bounded(monkeypatch):
    """The weather service degrades badly under a burst: never more than a few calls in flight."""
    in_flight = {"now": 0, "max": 0}

    async def _slow(request):
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        await asyncio.sleep(0.02)
        in_flight["now"] -= 1
        return httpx.Response(200, json={"ok": True})

    respx.get(url__regex=r".*/agro-status$").mock(side_effect=_slow)
    out = await asyncio.gather(*[ws.fetch_agro_status(TENANT, f"p{i}") for i in range(9)])
    assert all(o == {"ok": True} for o in out)
    assert in_flight["max"] <= ws._AGRO_MAX_CONCURRENT


@respx.mock
async def test_agro_status_is_cached_per_parcel_and_failures_are_not():
    route = respx.get(_url()).mock(return_value=httpx.Response(200, json={"a": 1}))
    assert await ws.fetch_agro_status(TENANT, SHORT) == {"a": 1}
    assert await ws.fetch_agro_status(TENANT, SHORT) == {"a": 1}
    assert route.call_count == 1
    other = respx.get(url__regex=r".*/other/agro-status$").mock(return_value=httpx.Response(503))
    assert await ws.fetch_agro_status(TENANT, "other") is None
    assert await ws.fetch_agro_status(TENANT, "other") is None
    assert other.call_count == 2


@respx.mock
async def test_agro_status_cache_is_per_tenant():
    route = respx.get(_url()).mock(return_value=httpx.Response(200, json={"a": 1}))
    await ws.fetch_agro_status(TENANT, SHORT)
    await ws.fetch_agro_status("tenant-b", SHORT)
    assert route.call_count == 2
