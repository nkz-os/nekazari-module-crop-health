"""Task 6 — sensor webhook does a deterministic full multi-zone recompute.

The webhook calls ``pipeline.trigger()`` which recomputes ALL zones of the
parcel (never a partial single-zone patch). This test locks in that contract:
a sensor measurement from ANY device on the parcel triggers a FULL recompute.
"""

import os
import pytest


# ---------------------------------------------------------------------------
# Module-level mocks — must be set BEFORE importing app.main
# (prevents Keycloak/JWKS HTTP requests on import)
# ---------------------------------------------------------------------------
os.environ.setdefault("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-secret")
os.environ.setdefault("API_PREFIX", "/api/crop-health")
os.environ.setdefault("KEYCLOAK_URL", "http://keycloak:8080/auth")


class _FakeRedis:
    async def store_reading(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    import app.main as _main
    monkeypatch.setattr(_main, "get_redis_state", lambda: _FakeRedis(), raising=False)


@pytest.mark.asyncio
async def test_webhook_calls_full_trigger(monkeypatch):
    """A webhook measurement MUST call pipeline.trigger (full recompute)."""
    calls = []

    async def _trigger(entity_id, metric_type, redis_state, parcel_id, tenant_id):
        calls.append((entity_id, metric_type, parcel_id, tenant_id))
        return None

    from app.api import webhooks
    monkeypatch.setattr(webhooks.pipeline, "trigger", _trigger, raising=False)
    monkeypatch.setattr(webhooks, "_validate_webhook_secret", lambda r: None, raising=False)

    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    payload = {
        "data": [
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:d1",
                "type": "DeviceMeasurement",
                "leafTemperature": {"type": "Property", "value": 28.5},
                "hasAgriParcel": {
                    "type": "Relationship",
                    "object": "urn:ngsi-ld:AgriParcel:p1",
                },
            }
        ]
    }
    response = client.post("/api/crop-health/webhooks/fiware-sensors", json=payload)
    assert response.status_code in (204, 200)
    assert len(calls) == 1
    _, metric_type, parcel_id, tenant_id = calls[0]
    assert metric_type == "leafTemperature"
    assert parcel_id == "p1"


@pytest.mark.asyncio
async def test_webhook_ignores_untracked_attributes(monkeypatch):
    """Attributes not in _TRACKED_ATTRIBUTES must not trigger the pipeline."""
    calls = []

    async def _trigger(*a, **k):
        calls.append(a)

    from app.api import webhooks
    monkeypatch.setattr(webhooks.pipeline, "trigger", _trigger, raising=False)
    monkeypatch.setattr(webhooks, "_validate_webhook_secret", lambda r: None, raising=False)

    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    payload = {
        "data": [
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:d1",
                "type": "DeviceMeasurement",
                "batteryLevel": {"type": "Property", "value": 85},
            }
        ]
    }
    response = client.post("/api/crop-health/webhooks/fiware-sensors", json=payload)
    assert not calls  # no trigger for untracked attrs
