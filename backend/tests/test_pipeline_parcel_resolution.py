"""The parcel comes from the device's `controlledAsset`, never from the entity id.

The old heuristic parsed `urn:ngsi-ld:DeviceMeasurement:{parcel}-{sensor}`, a
convention the canonical model no longer uses. Against a stable measurement id
(`...:{tenant}:{externalId}:{controlledProperty}`) it returns the TENANT as if it
were the parcel, and the pipeline then computes against a parcel that does not
exist — silently. It has to be gone, not adapted.
"""

import os

import pytest

os.environ.setdefault("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-secret")
os.environ.setdefault("KEYCLOAK_URL", "http://keycloak:8080/auth")

DEVICE_URN = "urn:ngsi-ld:Device:acme:probe-01"


def _fake_orion(device_entity, monkeypatch):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def get_entity(self, entity_id, options=None):
            if device_entity is None:
                raise RuntimeError("not found")
            return device_entity

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod

    monkeypatch.setattr(orion_mod, "OrionClient", _FakeClient)


def test_heuristic_is_gone():
    """No id-parsing fallback may survive — it silently returns the tenant."""
    from app.services import pipeline

    assert not hasattr(pipeline, "_extract_parcel_from_entity")


@pytest.mark.asyncio
async def test_resolves_parcel_from_controlled_asset(monkeypatch):
    from app.services import pipeline

    _fake_orion(
        {
            "id": DEVICE_URN,
            "type": "Device",
            "controlledAsset": {
                "type": "Relationship",
                "object": "urn:ngsi-ld:AgriParcel:acme:Parcela-4",
            },
        },
        monkeypatch,
    )
    assert await pipeline._resolve_parcel_from_device(DEVICE_URN, "acme") == "Parcela-4"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_attr", ["hasAgriParcel", "refAgriParcel"])
async def test_falls_back_to_legacy_relationship_names(monkeypatch, legacy_attr):
    """Migration window: devices provisioned before the cutover still carry these."""
    from app.services import pipeline

    _fake_orion(
        {
            "id": DEVICE_URN,
            "type": "Device",
            legacy_attr: {
                "type": "Relationship",
                "object": "urn:ngsi-ld:AgriParcel:acme:Parcela-9",
            },
        },
        monkeypatch,
    )
    assert await pipeline._resolve_parcel_from_device(DEVICE_URN, "acme") == "Parcela-9"


@pytest.mark.asyncio
async def test_unlinked_device_resolves_to_nothing(monkeypatch):
    """No link means no parcel. Never a guess."""
    from app.services import pipeline

    _fake_orion({"id": DEVICE_URN, "type": "Device"}, monkeypatch)
    assert await pipeline._resolve_parcel_from_device(DEVICE_URN, "acme") is None


@pytest.mark.asyncio
async def test_broker_failure_resolves_to_nothing(monkeypatch):
    """A broker error must not raise into the pipeline nor invent a parcel."""
    from app.services import pipeline

    _fake_orion(None, monkeypatch)
    assert await pipeline._resolve_parcel_from_device(DEVICE_URN, "acme") is None
