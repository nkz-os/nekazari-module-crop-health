from datetime import datetime, timezone

import pytest

from app.services import context_client
from app.services.zonation import Zone
from app.services.zone_inputs import gather_zone_inputs, wetness_class
from app.services.pipeline import _zone_soil_values

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
_SQ = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}


def _z(zid="z1", ver="v1", rank=1):
    return Zone(zone_id=zid, geometry=_SQ, zone_version=ver, zone_rank=rank)


async def _none(*a, **k):
    return {}


@pytest.mark.parametrize("wf,cls", [(0.05, "drained"), (0.1, "balanced"), (0.49, "balanced"), (0.5, "wet"), (0.9, "wet")])
def test_wetness_class(wf, cls):
    assert wetness_class(wf) == cls


@pytest.mark.asyncio
async def test_soil_endpoint_down_is_parcel_inherited():
    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [_z()], None, NOW,
        fetch_daily=_none, gather_sensors=_none, fetch_soil=_none, fetch_twi=_none,
    )
    zi = out["z1"]
    assert zi.soil is None and zi.twi is None
    assert zi.fidelity["soil"] == "parcel_inherited" and zi.fidelity["twi"] == "parcel_inherited"
    assert _zone_soil_values(zi.soil) == (None, None)


@pytest.mark.asyncio
async def test_zone_specific_soil_and_twi():
    async def soil(p, t, zones):
        return {"z1": {"zoneId": "z1", "fidelity": "zone_specific", "provider": "x",
                       "horizon": {"fieldCapacity": 0.34, "wiltingPoint": 0.15, "ksatSaturated": 8.0,
                                   "hydrologicGroup": "C", "clay": 30.0}}}

    async def twi(p, t, zones):
        return {"z1": {"zoneId": "z1", "fidelity": "zone_specific", "twiMean": 9.0,
                       "twiP90": 12.0, "wetFraction": 0.6, "slopeMean": 2.0, "flowAccumMax": 5}}

    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [_z()], None, NOW,
        fetch_daily=_none, gather_sensors=_none, fetch_soil=soil, fetch_twi=twi,
    )
    zi = out["z1"]
    assert zi.fidelity["soil"] == "zone_specific" and zi.fidelity["twi"] == "zone_specific"
    assert _zone_soil_values(zi.soil) == (0.34, 0.15)
    assert zi.soil["ksatSaturated"] == 8.0 and zi.soil["hydrologicGroup"] == "C"
    assert zi.twi["wetnessClass"] == "wet" and zi.twi["twiMean"] == 9.0


class _FakeRedis:
    def __init__(self):
        self.d = {}

    async def get_json(self, key):
        return self.d.get(key)

    async def set_json(self, key, value, ttl_s):
        self.d[key] = value
        return True


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


@pytest.mark.asyncio
async def test_cache_second_call_skips_endpoint(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(context_client, "_zone_cache", lambda: fake)
    calls = []

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            calls.append((url, json))
            return _Resp({"parcel_id": "p1", "zones": [
                {"zoneId": "z1", "zoneVersion": "v1", "fidelity": "zone_specific", "provider": "x",
                 "horizon": {"fieldCapacity": 0.34}}]})

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    zones = [_z()]
    a = await context_client.get_zone_soil("urn:p", "acme", zones, parcel_short="p1")
    b = await context_client.get_zone_soil("urn:p", "acme", zones, parcel_short="p1")
    assert len(calls) == 1
    assert a["z1"]["horizon"]["fieldCapacity"] == 0.34 == b["z1"]["horizon"]["fieldCapacity"]


@pytest.mark.asyncio
async def test_failures_return_empty(monkeypatch):
    monkeypatch.setattr(context_client, "_zone_cache", lambda: None)

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            r = _Resp({}); r.status_code = 404; return r

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    assert await context_client.get_zone_twi("urn:p", "acme", [_z()], parcel_short="p1") == {}
