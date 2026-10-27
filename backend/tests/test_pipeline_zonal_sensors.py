import sys
import types

import pytest

from app.services import context_client, pipeline
from app.services.zonation import Zone, consolidate_sensor_readings, sensors_in_zone

_PARCEL = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
_URN = "urn:ngsi-ld:AgriParcel:p1"


class _Pt:
    def __init__(self, v):
        self.value = v


class _FakeRedis:
    def __init__(self, data):
        self.data = data

    async def get_window(self, device_id, metric, hours=None):
        return [_Pt(v) for v in self.data.get((device_id, metric), [])]


def _point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


@pytest.fixture
def fake_orion(monkeypatch):
    devices = []

    class FakeOrion:
        def __init__(self, *a, **k):
            pass

        async def query_entities(self, **kw):
            assert kw["type"] == "Device"
            return devices

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod
    monkeypatch.setattr(orion_mod, "OrionClient", FakeOrion)
    return devices


@pytest.mark.asyncio
async def test_gathers_inside_device_only_and_consolidates(fake_orion):
    fake_orion += [
        {"id": "urn:Device:in1", "location": _point(2, 2)},
        {"id": "urn:Device:in2", "location": _point(3, 3)},
        {"id": "urn:Device:out", "location": _point(50, 50)},
    ]
    redis = _FakeRedis({
        ("urn:Device:in1", "airTemperature"): [20.0, 22.0],
        ("urn:Device:in2", "airTemperature"): [26.0],
        ("urn:Device:out", "airTemperature"): [99.0],
    })
    sensors = await pipeline._gather_parcel_sensors(
        _URN, "acme", redis_state=redis, parcel_geometry=_PARCEL
    )
    assert {s["device_id"] for s in sensors} == {"urn:Device:in1", "urn:Device:in2"}
    zone = Zone(zone_id="z1", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 5], [5, 5], [5, 0], [0, 0]]]})
    ctx = consolidate_sensor_readings(sensors_in_zone(zone, sensors))
    assert ctx["air_temp_c"] == pytest.approx(23.5)  # mean of 21 and 26


@pytest.mark.asyncio
async def test_controlled_asset_without_location_included_unattributed(fake_orion):
    fake_orion += [
        {"id": "urn:Device:c1", "controlledAsset": [_URN]},
        {"id": "urn:Device:c2", "controlledAsset": "urn:ngsi-ld:AgriParcel:other"},
    ]
    redis = _FakeRedis({("urn:Device:c1", "soilMoisture"): [30.0]})
    sensors = await pipeline._gather_parcel_sensors(
        _URN, "acme", redis_state=redis, parcel_geometry=_PARCEL
    )
    assert len(sensors) == 1
    assert sensors[0]["lon"] is None and sensors[0]["lat"] is None
    assert sensors[0]["readings"] == {"soil_moisture": 30.0}
    zone = Zone(zone_id="z1", geometry=_PARCEL)
    assert sensors_in_zone(zone, sensors) == []


@pytest.mark.asyncio
async def test_failure_returns_empty(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("down")

    import nkz_platform_sdk.orion as orion_mod
    monkeypatch.setattr(orion_mod, "OrionClient", Boom)
    assert await pipeline._gather_parcel_sensors(
        _URN, "acme", redis_state=_FakeRedis({}), parcel_geometry=_PARCEL
    ) == []
