"""The scheduled run refreshes milestone dates after each assessment and never lets that break the run."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import setup as setup_mod
from app.main import app


@pytest.fixture(autouse=True)
def _secret():
    original = setup_mod.INTERNAL_SECRET
    setup_mod.INTERNAL_SECRET = "s"
    yield
    setup_mod.INTERNAL_SECRET = original


def _run(monkeypatch, refresh, results):
    async def _list(tenant_id, cursor, batch_size):
        return (["urn:p1", "urn:p2"], None)

    async def _compute(parcel_id, tenant_id):
        return results[parcel_id]

    monkeypatch.setattr(setup_mod, "_list_active_crop_parcels", _list, raising=False)
    monkeypatch.setattr(setup_mod, "compute_assessment", _compute, raising=False)
    monkeypatch.setattr(setup_mod.phenology_dates, "refresh", refresh)
    r = TestClient(app).post("/api/crop-health/internal/run-scheduled-assessments",
                             headers={"X-Internal-Service-Secret": "s"},
                             json={"tenant_id": "tenant-a", "batch_size": 2})
    return r


def test_refresh_called_per_assessed_parcel_with_species(monkeypatch):
    calls = []

    async def _refresh(state, tenant, parcel, species):
        calls.append((tenant, parcel, species))
        return "written"

    r = _run(monkeypatch, _refresh, {"urn:p1": SimpleNamespace(crop_species="wheat"), "urn:p2": None})
    assert r.status_code == 200 and r.json()["written"] == 1 and r.json()["errors"] == []
    assert calls == [("tenant-a", "urn:p1", "wheat")]


def test_refresh_failure_does_not_change_the_run(monkeypatch):
    async def _refresh(*a):
        raise RuntimeError("boom")

    r = _run(monkeypatch, _refresh, {"urn:p1": SimpleNamespace(crop_species="wheat"),
                                     "urn:p2": SimpleNamespace(crop_species="wheat")})
    assert r.status_code == 200
    assert r.json()["written"] == 2 and r.json()["errors"] == []


def test_no_species_no_refresh(monkeypatch):
    async def _refresh(*a):
        raise AssertionError("must not be called")

    r = _run(monkeypatch, _refresh, {"urn:p1": SimpleNamespace(crop_species=None), "urn:p2": object()})
    assert r.status_code == 200 and r.json()["written"] == 2


def _run_n(monkeypatch, refresh, n, species="wheat"):
    ids = [f"urn:p{i}" for i in range(n)]

    async def _list(tenant_id, cursor, batch_size):
        return (ids, None)

    async def _compute(parcel_id, tenant_id):
        return SimpleNamespace(crop_species=species)

    monkeypatch.setattr(setup_mod, "_list_active_crop_parcels", _list, raising=False)
    monkeypatch.setattr(setup_mod, "compute_assessment", _compute, raising=False)
    monkeypatch.setattr(setup_mod.phenology_dates, "refresh", refresh)
    return TestClient(app).post("/api/crop-health/internal/run-scheduled-assessments",
                                headers={"X-Internal-Service-Secret": "s"},
                                json={"tenant_id": "tenant-a", "batch_size": n})


def test_three_consecutive_failures_stop_refreshing_for_the_batch(monkeypatch, caplog):
    calls = []

    async def _refresh(state, tenant, parcel, species):
        calls.append(parcel)
        return "failed"

    with caplog.at_level("WARNING"):
        r = _run_n(monkeypatch, _refresh, 6)
    assert r.status_code == 200 and r.json()["written"] == 6 and r.json()["errors"] == []
    assert calls == ["urn:p0", "urn:p1", "urn:p2"]
    stops = [x for x in caplog.records if "stopping" in x.getMessage()]
    assert len(stops) == 1 and "tenant=tenant-a" in stops[0].getMessage()


def test_a_success_resets_the_failure_count(monkeypatch):
    outcomes = iter(["failed", "failed", "written", "failed", "failed", "written"])
    calls = []

    async def _refresh(state, tenant, parcel, species):
        calls.append(parcel)
        return next(outcomes)

    r = _run_n(monkeypatch, _refresh, 6)
    assert r.status_code == 200 and len(calls) == 6


def test_exceptions_count_as_failures(monkeypatch):
    calls = []

    async def _refresh(*a):
        calls.append(1)
        raise RuntimeError("boom")

    r = _run_n(monkeypatch, _refresh, 5)
    assert r.status_code == 200 and r.json()["written"] == 5 and len(calls) == 3
