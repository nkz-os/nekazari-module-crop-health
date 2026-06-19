import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import setup as setup_mod


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_internal_secret():
    """Tests mutate setup_mod.INTERNAL_SECRET; restore it so other test modules
    that rely on the configured value aren't contaminated."""
    original = setup_mod.INTERNAL_SECRET
    yield
    setup_mod.INTERNAL_SECRET = original


def test_rejects_without_secret(client):
    r = client.post("/api/crop-health/internal/run-scheduled-assessments", json={"tenant_id": "t"})
    assert r.status_code == 401


def test_bounded_page_and_cursor(client, monkeypatch):
    setup_mod.INTERNAL_SECRET = "s"  # ensure configured

    async def _list_active(tenant_id, cursor, batch_size):
        # page 1 returns 2 parcels + a next cursor; assert batch_size respected
        assert batch_size == 2
        return (["urn:p1", "urn:p2"], "cur2")

    calls = []

    async def _compute(parcel_id, tenant_id):
        calls.append(parcel_id)

        class A:
            pass

        return A()

    monkeypatch.setattr(setup_mod, "_list_active_crop_parcels", _list_active, raising=False)
    monkeypatch.setattr(setup_mod, "compute_assessment", _compute, raising=False)
    r = client.post(
        "/api/crop-health/internal/run-scheduled-assessments",
        headers={"X-Internal-Service-Secret": "s"},
        json={"tenant_id": "t", "batch_size": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["processed"] == 2
    assert body["next_cursor"] == "cur2"
    assert calls == ["urn:p1", "urn:p2"]


def test_per_parcel_error_isolation(client, monkeypatch):
    setup_mod.INTERNAL_SECRET = "s"

    async def _list_active(tenant_id, cursor, batch_size):
        return (["urn:ok", "urn:boom"], None)

    async def _compute(parcel_id, tenant_id):
        if parcel_id == "urn:boom":
            raise RuntimeError("kaboom")

        class A:
            pass

        return A()

    monkeypatch.setattr(setup_mod, "_list_active_crop_parcels", _list_active, raising=False)
    monkeypatch.setattr(setup_mod, "compute_assessment", _compute, raising=False)
    r = client.post(
        "/api/crop-health/internal/run-scheduled-assessments",
        headers={"X-Internal-Service-Secret": "s"},
        json={"tenant_id": "t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["written"] == 1
    assert len(body["errors"]) == 1
    assert body["next_cursor"] is None
