import pytest

from app.services.parcel_link import owner_from_link

PARK = "urn:ngsi-ld:AgriSolarPark:x"
P1 = "urn:ngsi-ld:AgriParcel:acme-p1"
P2 = "urn:ngsi-ld:AgriParcel:p2"
DEVICE = "urn:ngsi-ld:Device:acme:s1"


def test_owner_park_first_with_parcel():
    link = {"type": "Relationship", "object": [PARK, P1]}
    assert owner_from_link(link) == ("under_panel", P1, PARK)


def test_owner_park_only():
    assert owner_from_link({"object": [PARK]}) == ("under_panel", None, PARK)


def test_owner_parcel_bare_string():
    assert owner_from_link("urn:ngsi-ld:AgriParcel:p1") == ("open_field", "urn:ngsi-ld:AgriParcel:p1", None)


def test_owner_first_parcel_wins():
    assert owner_from_link({"object": [P2, "urn:ngsi-ld:AgriParcel:p3"]})[1] == P2


def test_owner_unknown_or_empty():
    assert owner_from_link({"object": ["urn:ngsi-ld:Building:b"]}) is None
    assert owner_from_link({"object": []}) is None
    assert owner_from_link(None) is None


def _fake(monkeypatch, device, park=None, park_raises=False):
    calls = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def get_entity(self, entity_id, options=None):
            calls.append(entity_id)
            if entity_id == DEVICE:
                return device
            if park_raises:
                raise RuntimeError("boom")
            return park

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod

    monkeypatch.setattr(orion_mod, "OrionClient", _Client)
    return calls


@pytest.mark.asyncio
async def test_resolve_park_and_parcel_no_park_fetch(monkeypatch):
    from app.services import pipeline

    calls = _fake(monkeypatch, {"controlledAsset": {"type": "Relationship", "object": [PARK, P1]}})
    assert await pipeline._resolve_device_owner(DEVICE, "acme") == ("acme-p1", "under_panel")
    assert calls == [DEVICE]


@pytest.mark.asyncio
async def test_resolve_park_only_hops_to_park(monkeypatch):
    from app.services import pipeline

    park = {"hasAgriParcel": {"type": "Relationship", "object": P1}}
    calls = _fake(monkeypatch, {"controlledAsset": {"object": PARK}}, park=park)
    assert await pipeline._resolve_device_owner(DEVICE, "acme") == ("acme-p1", "under_panel")
    assert calls == [DEVICE, PARK]


@pytest.mark.asyncio
async def test_resolve_park_fetch_fails(monkeypatch):
    from app.services import pipeline

    _fake(monkeypatch, {"controlledAsset": {"object": PARK}}, park_raises=True)
    assert await pipeline._resolve_device_owner(DEVICE, "acme") is None


@pytest.mark.asyncio
async def test_resolve_park_without_parcel(monkeypatch):
    from app.services import pipeline

    _fake(monkeypatch, {"controlledAsset": {"object": PARK}}, park={"id": PARK})
    assert await pipeline._resolve_device_owner(DEVICE, "acme") is None


@pytest.mark.asyncio
async def test_resolve_legacy_is_open_field(monkeypatch):
    from app.services import pipeline

    _fake(monkeypatch, {"hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"}})
    assert await pipeline._resolve_device_owner(DEVICE, "acme") == ("p1", "open_field")


@pytest.mark.asyncio
async def test_resolve_building_first_ignored(monkeypatch):
    from app.services import pipeline

    _fake(monkeypatch, {"controlledAsset": {"object": ["urn:ngsi-ld:Building:b", P1]}})
    assert await pipeline._resolve_device_owner(DEVICE, "acme") is None


@pytest.mark.asyncio
async def test_resolve_empty_link_falls_back_to_legacy(monkeypatch):
    from app.services import pipeline

    _fake(monkeypatch, {"controlledAsset": {"type": "Relationship", "object": []},
                        "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"}})
    assert await pipeline._resolve_device_owner(DEVICE, "acme") == ("p1", "open_field")
