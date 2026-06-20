"""Test phenology-status API endpoints — read-only GET + explicit POST sync."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        c = TestClient(app)
        # AuthMiddleware trusts gateway-injected identity headers
        c.headers.update({"X-Tenant-ID": "test-tenant", "X-User-ID": "test-user"})
        return c


def test_get_is_read_only_no_orion_writes(client, monkeypatch):
    from app.api import phenology

    writes = []

    async def _latest(parcel_id, tenant_id):
        return {
            "id": "urn:ngsi-ld:CropHealthAssessment:p1-2026-06-19",
            "gddAccumulated": 300.0,
            "phenologyStage": "vegetative",
            "species": "Zea mays",
            "seasonStart": "2026-04-15",
        }

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages={"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0)})

    async def _no_write(*args, **kwargs):
        writes.append("x")
        raise AssertionError("GET must never write to Orion")

    monkeypatch.setattr(phenology, "_read_latest_assessment", _latest)
    monkeypatch.setattr(phenology.context_client, "get_phenology_stages", _stages)
    # Any Orion write seam reachable from the GET path must never be invoked.
    monkeypatch.setattr(phenology, "compute_assessment", _no_write)
    monkeypatch.setattr("app.services.pipeline._publish_assessment", _no_write)

    r = client.get(
        "/api/crop-health/parcels/urn:ngsi-ld:AgriParcel:t:p1/phenology-status",
        headers={"X-Tenant-ID": "t", "X-User-ID": "test-user"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["currentStage"] == "vegetative"
    assert "stages" in body
    assert writes == []  # GET performed zero writes


def test_get_pending_when_no_assessment(client, monkeypatch):
    from app.api import phenology

    async def _none(parcel_id, tenant_id):
        return None

    monkeypatch.setattr(phenology, "_read_latest_assessment", _none)
    r = client.get(
        "/api/crop-health/parcels/urn:ngsi-ld:AgriParcel:t:p1/phenology-status",
        headers={"X-Tenant-ID": "t", "X-User-ID": "test-user"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_sync_calls_compute_assessment_and_returns_status(client, monkeypatch):
    from app.api import phenology
    from app.schemas import CropHealthAssessment
    from datetime import datetime, timezone

    called = {}

    async def _compute(parcel_id, tenant_id, **kwargs):
        called["parcel_id"] = parcel_id
        called["tenant_id"] = tenant_id
        return CropHealthAssessment(
            parcel_id=parcel_id,
            assessed_at=datetime.now(timezone.utc),
            crop_species="Zea mays",
            phenology_stage="vegetative",
            gdd_accumulated=300.0,
        )

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages={"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0)})

    monkeypatch.setattr(phenology, "compute_assessment", _compute)
    monkeypatch.setattr(phenology.context_client, "get_phenology_stages", _stages)

    r = client.post(
        "/api/crop-health/parcels/urn:ngsi-ld:AgriParcel:t:p1/phenology-status/sync",
        headers={"X-Tenant-ID": "t", "X-User-ID": "test-user"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["currentStage"] == "vegetative"
    assert called["tenant_id"] == "t"


def test_sync_returns_no_crop_when_assessment_is_none(client, monkeypatch):
    from app.api import phenology

    async def _compute(parcel_id, tenant_id, **kwargs):
        return None

    monkeypatch.setattr(phenology, "compute_assessment", _compute)

    r = client.post(
        "/api/crop-health/parcels/urn:ngsi-ld:AgriParcel:t:p1/phenology-status/sync",
        headers={"X-Tenant-ID": "t", "X-User-ID": "test-user"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "no_crop"
