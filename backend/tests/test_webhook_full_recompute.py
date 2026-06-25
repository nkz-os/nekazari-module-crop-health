"""Task 6 — sensor webhook does a deterministic full multi-zone recompute.

The webhook calls ``pipeline.trigger()`` which recomputes ALL zones of the
parcel (never a partial single-zone patch). This test locks in that contract:
a sensor measurement from ANY device on the parcel triggers a FULL recompute.
"""

import pytest


class _FakeRedis:
    async def store_reading(self, *a, **k):
        pass


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

    import app.main as app_main
    monkeypatch.setattr(app_main, "get_redis_state", lambda: _FakeRedis(), raising=False)

    from fastapi.testclient import TestClient

    client = TestClient(webhooks.router)
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
    response = client.post("/webhooks/fiware-sensors", json=payload)
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

    import app.main as app_main
    monkeypatch.setattr(app_main, "get_redis_state", lambda: _FakeRedis(), raising=False)

    from fastapi.testclient import TestClient

    client = TestClient(webhooks.router)
    payload = {
        "data": [
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:d1",
                "type": "DeviceMeasurement",
                "batteryLevel": {"type": "Property", "value": 85},
            }
        ]
    }
    response = client.post("/webhooks/fiware-sensors", json=payload)
    assert not calls  # no trigger for untracked attrs
