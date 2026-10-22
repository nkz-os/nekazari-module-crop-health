import pytest

from app.services.zonation import resolve_zones, is_whole_parcel, Zone

_PARCEL_GEOM = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}


class _FakeOrion:
    def __init__(self, zones):
        self._zones = zones

    async def query_entities(self, **kw):
        return self._zones

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_resolve_zones_from_agriparcelzone(monkeypatch):
    # Real weather-map shape: nkz:-prefixed attrs, colon-separated tenant-scoped URN,
    # boolean sensorNearby, keyValues location = geometry dict.
    z = [{
        "id": "urn:ngsi-ld:AgriParcelZone:t:p1:zABC-e3-N",
        "nkz:zoneId": "zABC-e3-N",
        "location": _PARCEL_GEOM,
        "nkz:sensorNearby": True,
        "nkz:centroid": [0.5, 0.5],
    }]
    monkeypatch.setattr("app.services.zonation._orion", lambda t: _FakeOrion(z))
    zones = await resolve_zones("urn:ngsi-ld:AgriParcel:p1", "t", _PARCEL_GEOM)
    assert len(zones) == 1
    assert zones[0].zone_id == "zABC-e3-N"
    assert zones[0].urn == "urn:ngsi-ld:AgriParcelZone:t:p1:zABC-e3-N"
    assert zones[0].sensor_nearby is True
    assert zones[0].centroid == (0.5, 0.5)
    assert not is_whole_parcel(zones)


@pytest.mark.asyncio
async def test_resolve_zones_compacted_keys(monkeypatch):
    # If the @context compacts nkz: away, the unprefixed keys must also work,
    # and zoneId falls back to the URN's last colon segment.
    z = [{"id": "urn:ngsi-ld:AgriParcelZone:t:p1:z0", "location": _PARCEL_GEOM}]
    monkeypatch.setattr("app.services.zonation._orion", lambda t: _FakeOrion(z))
    zones = await resolve_zones("urn:ngsi-ld:AgriParcel:p1", "t", _PARCEL_GEOM)
    assert len(zones) == 1 and zones[0].zone_id == "z0"


@pytest.mark.asyncio
async def test_resolve_zones_fallback_whole_parcel(monkeypatch):
    monkeypatch.setattr("app.services.zonation._orion", lambda t: _FakeOrion([]))
    zones = await resolve_zones("urn:ngsi-ld:AgriParcel:p1", "t", _PARCEL_GEOM)
    assert len(zones) == 1 and zones[0].zone_id == "parcel"
    assert zones[0].geometry == _PARCEL_GEOM
    assert is_whole_parcel(zones)


@pytest.mark.asyncio
async def test_resolve_zones_sorted_deterministic(monkeypatch):
    z = [
        {"id": "urn:ngsi-ld:AgriParcelZone:t:p1:z2", "nkz:zoneId": "z2", "location": _PARCEL_GEOM},
        {"id": "urn:ngsi-ld:AgriParcelZone:t:p1:z1", "nkz:zoneId": "z1", "location": _PARCEL_GEOM},
    ]
    monkeypatch.setattr("app.services.zonation._orion", lambda t: _FakeOrion(z))
    zones = await resolve_zones("urn:ngsi-ld:AgriParcel:p1", "t", _PARCEL_GEOM)
    assert [zn.zone_id for zn in zones] == ["z1", "z2"]
