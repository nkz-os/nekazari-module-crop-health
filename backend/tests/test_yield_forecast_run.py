"""Nightly worker: every AgriParcel, store rules, locks, internal auth."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import yield_forecast


class FakeState:
    def __init__(self):
        self.data, self.locks = {}, set()
        self.available = True

    async def get_json(self, k):
        return self.data.get(k)

    async def set_json(self, k, v, ttl_s):
        self.data[k] = v
        return True

    async def try_lock(self, k, ttl_s):
        if k in self.locks:
            return False
        self.locks.add(k)
        return True

    async def unlock(self, k):
        self.locks.discard(k)

    async def is_locked(self, k):
        return k in self.locks


URN = "urn:ngsi-ld:AgriParcel:p1"
DONE = {"state": "done", "estimates": [{"provider_id": "aquacrop"}], "season": None, "unavailable": []}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_compute_writes_done():
    st = FakeState()
    with patch.object(yield_forecast, "fetch_in_season", AsyncMock(return_value=DONE)):
        out = await yield_forecast.compute_and_store(st, "tenant-a", "p1")
    assert out == "written"
    assert st.data[f"yield-forecast:tenant-a:{URN}"]["status"] == "done"
    assert not st.locks


@pytest.mark.anyio
async def test_worker_skips_locked_parcel():
    st = FakeState()
    st.locks.add(f"yield-forecast-lock:tenant-a:{URN}")
    fetch = AsyncMock(return_value=DONE)
    with patch.object(yield_forecast, "fetch_in_season", fetch):
        out = await yield_forecast.compute_and_store(st, "tenant-a", "p1")
    assert out == "skipped_locked" and fetch.await_count == 0


@pytest.mark.anyio
async def test_busy_keeps_store():
    st = FakeState()
    st.data[f"yield-forecast:tenant-a:{URN}"] = {"status": "done", "estimates": [1]}
    busy = {"state": "unavailable", "unavailable": [{"reason": "busy"}]}
    with patch.object(yield_forecast, "fetch_in_season", AsyncMock(return_value=busy)):
        out = await yield_forecast.compute_and_store(st, "tenant-a", "p1")
    assert out == "kept" and st.data[f"yield-forecast:tenant-a:{URN}"]["estimates"] == [1]


def _client(monkeypatch, state, parcels):
    from app.api import setup
    monkeypatch.setattr(setup, "INTERNAL_SECRET", "real-secret")
    monkeypatch.setattr(setup, "_list_all_parcels", AsyncMock(return_value=parcels))
    monkeypatch.setattr("app.main.get_redis_state", lambda: state)
    return TestClient(app)


def test_run_requires_secret(monkeypatch):
    c = _client(monkeypatch, FakeState(), ([], None))
    r = c.post("/api/crop-health/internal/run-yield-forecasts", json={"tenant_id": "tenant-a"},
               headers={"X-Internal-Service-Secret": "wrong"})
    assert r.status_code == 401


def test_run_one_failure_does_not_abort(monkeypatch):
    st = FakeState()
    c = _client(monkeypatch, st, (["urn:ngsi-ld:AgriParcel:a", "urn:ngsi-ld:AgriParcel:b"], "2"))

    async def fake(state, tenant, pid, **kw):
        if pid.endswith(":a"):
            raise RuntimeError("boom")
        return "written"

    monkeypatch.setattr("app.api.setup.compute_and_store", fake)
    r = c.post("/api/crop-health/internal/run-yield-forecasts",
               json={"tenant_id": "tenant-a", "batch_size": 2},
               headers={"X-Internal-Service-Secret": "real-secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["processed"] == 2 and body["written"] == 1 and body["next_cursor"] == "2"
    assert body["errors"][0]["parcel_id"].endswith(":a")


@pytest.mark.anyio
async def test_list_all_parcels_has_no_crop_filter(monkeypatch):
    from app.api import setup
    calls = {}

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def query_entities(self, **kw):
            calls.update(kw)
            return [{"id": "urn:ngsi-ld:AgriParcel:a"}]
        async def close(self): ...

    monkeypatch.setattr("nkz_platform_sdk.orion.OrionClient", FakeOrion)
    ids, nxt = await setup._list_all_parcels("tenant-a", None, 1)
    assert ids == ["urn:ngsi-ld:AgriParcel:a"] and nxt == "1"
    assert calls["type"] == "AgriParcel" and calls.get("q") is None


@pytest.mark.anyio
async def test_unreadable_previous_never_overwritten():
    from app.services.redis_state import StoreError

    class ReadFails(FakeState):
        async def get_json(self, k):
            raise StoreError("down")

    st = ReadFails()
    failed = {"state": "failed", "unavailable": [{"reason": "engine_error", "code": "x"}]}
    with patch.object(yield_forecast, "fetch_in_season", AsyncMock(return_value=failed)):
        out = await yield_forecast.compute_and_store(st, "tenant-a", "p1")
    assert out == "store_error" and st.data == {}


@pytest.mark.anyio
async def test_unknown_parcel_404_writes_nothing():
    st = FakeState()
    nf = {"state": "failed", "unavailable": [{"reason": "request_failed", "code": "404"}]}
    with patch.object(yield_forecast, "fetch_in_season", AsyncMock(return_value=nf)):
        out = await yield_forecast.compute_and_store(st, "tenant-a", "p1")
    assert out == "kept" and st.data == {}


@pytest.mark.anyio
async def test_retry_is_passed_through():
    st = FakeState()
    fetch = AsyncMock(return_value=DONE)
    with patch.object(yield_forecast, "fetch_in_season", fetch):
        await yield_forecast.compute_and_store(st, "tenant-a", "p1", retry=True)
    assert fetch.await_args.kwargs.get("retry") is True


@pytest.mark.anyio
async def test_list_all_parcels_requests_no_attrs(monkeypatch):
    from app.api import setup
    calls = {}

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def query_entities(self, **kw):
            calls.update(kw)
            return []
        async def close(self): ...

    monkeypatch.setattr("nkz_platform_sdk.orion.OrionClient", FakeOrion)
    await setup._list_all_parcels("tenant-a", None, 1)
    assert "attrs" not in calls
