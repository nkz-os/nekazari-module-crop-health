"""The webhook must read the canonical `DeviceMeasurement` shape.

`DeviceMeasurement` inverts the shape the handler used to expect: the measured
property's name is the VALUE of `controlledProperty` (not an attribute key), the
reading lives in `numValue`/`textValue`, the device is `refDevice` (not the last
segment of the entity id — that segment is the property name), and the instant is
`dateObserved`. Reading it the old way means the pipeline never fires at all.
"""

import os

import pytest

os.environ.setdefault("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-secret")
os.environ.setdefault("API_PREFIX", "/api/crop-health")
os.environ.setdefault("KEYCLOAK_URL", "http://keycloak:8080/auth")

DEVICE_URN = "urn:ngsi-ld:Device:acme:probe-01"


class _FakeRedis:
    def __init__(self):
        self.readings = []

    async def store_reading(self, device_id, metric, timestamp, value):
        self.readings.append((device_id, metric, timestamp, value))


@pytest.fixture
def fake_redis(monkeypatch):
    redis = _FakeRedis()
    import app.main as _main

    monkeypatch.setattr(_main, "get_redis_state", lambda: redis, raising=False)
    return redis


@pytest.fixture
def triggers(monkeypatch):
    calls = []

    async def _trigger(entity_id, metric_type, redis_state, parcel_id, tenant_id):
        calls.append(
            {
                "entity_id": entity_id,
                "metric_type": metric_type,
                "parcel_id": parcel_id,
                "tenant_id": tenant_id,
            }
        )
        return None

    from app.api import webhooks

    monkeypatch.setattr(webhooks.pipeline, "trigger", _trigger, raising=False)
    monkeypatch.setattr(webhooks, "_validate_webhook_secret", lambda r: None, raising=False)
    return calls


def _post(payload):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app).post(
        "/api/crop-health/webhooks/fiware-sensors",
        json=payload,
        headers={"Fiware-Service": "acme"},
    )


def _measurement(**overrides):
    entity = {
        "id": "urn:ngsi-ld:DeviceMeasurement:acme:probe-01:leafTemperature",
        "type": "DeviceMeasurement",
        "refDevice": {"type": "Relationship", "object": DEVICE_URN},
        "controlledProperty": {"type": "Property", "value": "leafTemperature"},
        "numValue": {"type": "Property", "value": 28.5, "unitCode": "CEL"},
        "dateObserved": {"type": "Property", "value": "2026-08-29T09:00:00Z"},
    }
    entity.update(overrides)
    return entity


def test_reads_property_name_value_and_device(fake_redis, triggers):
    """The metric comes from controlledProperty, the value from numValue, the
    device from refDevice — never from the measurement entity's own id."""
    resp = _post({"data": [_measurement()]})
    assert resp.status_code == 204

    assert len(triggers) == 1, "the pipeline must fire for a tracked property"
    assert triggers[0]["entity_id"] == DEVICE_URN
    assert triggers[0]["metric_type"] == "leafTemperature"
    assert triggers[0]["tenant_id"] == "acme"

    assert fake_redis.readings == [(DEVICE_URN, "leafTemperature", pytest.approx(1787994000.0), 28.5)]


def test_uses_date_observed_not_arrival_time(fake_redis, triggers):
    """The reading's instant is dateObserved, not when the notification landed."""
    _post({"data": [_measurement(dateObserved={"type": "Property", "value": "2026-08-29T10:30:00Z"})]})
    assert fake_redis.readings[0][2] == pytest.approx(1787999400.0)


def test_untracked_property_is_ignored(fake_redis, triggers):
    """A property we do not model must not reach Redis or the pipeline."""
    _post({"data": [_measurement(controlledProperty={"type": "Property", "value": "batteryLevel"})]})
    assert triggers == []
    assert fake_redis.readings == []


@pytest.mark.parametrize(
    "broken",
    [
        {"refDevice": None},
        {"refDevice": {"type": "Relationship", "object": ""}},
        {"numValue": None},
        {"controlledProperty": None},
    ],
    ids=["no-refDevice", "empty-refDevice", "no-value", "no-property-name"],
)
def test_incomplete_measurement_persists_nothing(fake_redis, triggers, broken):
    """Missing device or reading means nothing safe to persist — never a guessed id."""
    entity = _measurement()
    for key, value in broken.items():
        if value is None:
            entity.pop(key, None)
        else:
            entity[key] = value

    resp = _post({"data": [entity]})
    assert resp.status_code == 204
    assert triggers == []
    assert fake_redis.readings == []
