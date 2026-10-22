"""User routes: stored record, refresh lock, gateway identity."""
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from tests.test_yield_forecast_run import FakeState

H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URN = "urn:ngsi-ld:AgriParcel:d2e55461-eeb2-411d-b5f6-2f026e536914"
BARE = "d2e55461-eeb2-411d-b5f6-2f026e536914"


def _client(monkeypatch, state):
    monkeypatch.setattr("app.api.yield_forecast.get_redis_state", lambda: state)
    return TestClient(app)


def test_get_not_computed(monkeypatch):
    c = _client(monkeypatch, FakeState())
    r = c.get(f"/api/crop-health/parcels/{BARE}/yield-forecast", headers=H)
    assert r.status_code == 200 and r.json() == {"status": "not_computed", "refreshing": False}


def test_get_normalises_bare_id(monkeypatch):
    st = FakeState()
    st.data[f"yield-forecast:tenant-a:{URN}"] = {"status": "done", "estimates": []}
    c = _client(monkeypatch, st)
    assert c.get(f"/api/crop-health/parcels/{BARE}/yield-forecast", headers=H).json()["status"] == "done"
    assert c.get(f"/api/crop-health/parcels/{URN}/yield-forecast", headers=H).json()["status"] == "done"


def test_get_is_tenant_scoped(monkeypatch):
    st = FakeState()
    st.data[f"yield-forecast:tenant-b:{URN}"] = {"status": "done", "estimates": []}
    c = _client(monkeypatch, st)
    assert c.get(f"/api/crop-health/parcels/{URN}/yield-forecast", headers=H).json()["status"] == "not_computed"


def test_get_store_down(monkeypatch):
    st = FakeState()
    st.available = False
    c = _client(monkeypatch, st)
    r = c.get(f"/api/crop-health/parcels/{URN}/yield-forecast", headers=H)
    assert r.status_code == 200
    assert r.json() == {"status": "unavailable", "reason": "store_unavailable", "refreshing": False}


def test_refresh_twice_starts_once(monkeypatch):
    st = FakeState()
    run = AsyncMock(return_value="written")
    monkeypatch.setattr("app.api.yield_forecast.compute_and_store", run)
    c = _client(monkeypatch, st)
    st.locks.add(f"yield-forecast-lock:tenant-a:{URN}")  # a refresh already running
    r = c.post(f"/api/crop-health/parcels/{URN}/yield-forecast/refresh", headers=H)
    assert r.status_code == 202 and r.json() == {"refreshing": True}
    assert run.await_count == 0


def test_refresh_runs_and_releases(monkeypatch):
    st = FakeState()
    run = AsyncMock(return_value="written")
    monkeypatch.setattr("app.api.yield_forecast.compute_and_store", run)
    c = _client(monkeypatch, st)
    r = c.post(f"/api/crop-health/parcels/{BARE}/yield-forecast/refresh", headers=H)
    assert r.status_code == 202
    run.assert_awaited_once()
    assert run.await_args.kwargs == {"hold_lock": False, "retry": True}
    assert run.await_args.args[1:] == ("tenant-a", URN)
    assert not st.locks


def test_routes_need_identity(monkeypatch):
    c = _client(monkeypatch, FakeState())
    assert c.get(f"/api/crop-health/parcels/{URN}/yield-forecast").status_code == 401


def test_refresh_asks_bioorch_to_retry(monkeypatch):
    st = FakeState()
    run = AsyncMock(return_value="written")
    monkeypatch.setattr("app.api.yield_forecast.compute_and_store", run)
    c = _client(monkeypatch, st)
    c.post(f"/api/crop-health/parcels/{URN}/yield-forecast/refresh", headers=H)
    assert run.await_args.kwargs == {"hold_lock": False, "retry": True}


def test_invalid_parcel_id_rejected(monkeypatch):
    run = AsyncMock(return_value="written")
    monkeypatch.setattr("app.api.yield_forecast.compute_and_store", run)
    c = _client(monkeypatch, FakeState())
    bad = "x" * 300
    assert c.post(f"/api/crop-health/parcels/{bad}/yield-forecast/refresh", headers=H).status_code == 422
    assert c.get(f"/api/crop-health/parcels/a%20b/yield-forecast", headers=H).status_code == 422
    assert run.await_count == 0


def test_get_store_error_is_unavailable(monkeypatch):
    from app.services.redis_state import StoreError

    class ReadFails(FakeState):
        async def get_json(self, k):
            raise StoreError("down")

    c = _client(monkeypatch, ReadFails())
    r = c.get(f"/api/crop-health/parcels/{URN}/yield-forecast", headers=H)
    assert r.status_code == 200 and r.json()["reason"] == "store_unavailable"
