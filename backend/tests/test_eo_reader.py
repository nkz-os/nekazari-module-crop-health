"""Shared satellite reader: one broker read per target, failures never cached, SDK vocabulary."""
import asyncio
from unittest.mock import patch

import pytest
from nkz_platform_sdk import EO_FAMILIES, EO_VALUE_NAMES

from app.services import eo_reader
from tests.test_pipeline_zone_products import FakeOrion, PARCEL_URN, ZONE_URN


def _product(owner_attr, owner, day, **values):
    return {"id": f"urn:ngsi-ld:EOProduct:acme:{owner.rsplit(':', 1)[-1]}:{day}", "type": "EOProduct",
            owner_attr: owner, "sensingDate": day, **values}


def test_names_and_families_are_in_the_sdk_vocabulary():
    assert eo_reader.USED_FAMILIES <= set(EO_FAMILIES)
    assert eo_reader.USED_NAMES <= set(EO_VALUE_NAMES)
    assert eo_reader.NDVI_FAMILIES == {"s2-indices"}  # composites are never mixed into NDVI


@pytest.mark.asyncio
async def test_one_read_per_target_and_parcel_never_sees_zone_products():
    fo = FakeOrion([
        _product("hasAgriParcel", PARCEL_URN, "2026-06-01", ndvi=0.5),
        _product("hasAgriManagementZone", ZONE_URN, "2026-06-02", ndvi=0.9),
    ])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        first = await eo_reader.observations("acme", parcel_id="p1")
        n = len(fo.queries)
        again = await eo_reader.observations("acme", parcel_id="p1")
        zone = await eo_reader.observations("acme", zone_urn=ZONE_URN)
    assert len(fo.queries) > n  # the zone is its own read
    assert again is first and n == 2  # second parcel call answered from memory
    assert [o.values["ndvi"] for o in first] == [0.5]
    assert [o.values["ndvi"] for o in zone] == [0.9]


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_read():
    fo = FakeOrion([_product("hasAgriParcel", PARCEL_URN, "2026-06-01", ndvi=0.5)])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        results = await asyncio.gather(*(eo_reader.observations("acme", parcel_id="p1") for _ in range(5)))
    assert len(fo.queries) == 2 and all(r == results[0] for r in results)


@pytest.mark.asyncio
async def test_a_failed_read_raises_and_is_not_cached():
    class Boom:
        async def query_entities(self, **kw):
            raise RuntimeError("orion down")

        async def close(self):
            pass

    with patch("nkz_platform_sdk.orion.OrionClient", return_value=Boom()):
        with pytest.raises(RuntimeError):
            await eo_reader.observations("acme", parcel_id="p1")
    fo = FakeOrion([_product("hasAgriParcel", PARCEL_URN, "2026-06-01", ndvi=0.5)])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        assert len(await eo_reader.observations("acme", parcel_id="p1")) == 1


@pytest.mark.asyncio
async def test_newest_takes_the_later_of_two_lst_families():
    fo = FakeOrion([
        _product("hasAgriParcel", PARCEL_URN, "2026-06-01", lst=30.0, lstSourceScene="LC09_X"),
        _product("hasAgriParcel", PARCEL_URN, "2026-06-04", lst=27.5, lstSourceScene="CLMS:LST_X"),
    ])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        obs = await eo_reader.observations("acme", parcel_id="p1")
    o = eo_reader.newest(obs, families=eo_reader.LST_FAMILIES, require={eo_reader.LST})
    assert {x.family for x in obs} == {"landsat-lst", "clms-lst"}
    assert (o.family, eo_reader.number(o, eo_reader.LST)) == ("clms-lst", 27.5)


def test_target_is_one_of_parcel_or_zone():
    with pytest.raises(ValueError):
        asyncio.run(eo_reader.observations("acme"))
    with pytest.raises(ValueError):
        asyncio.run(eo_reader.observations("acme", parcel_id="p1", zone_urn=ZONE_URN))


# ── normalized fixtures, both stored shapes ──────────────────────────────────

def _prop(v):
    return {"type": "Property", "value": v}


def _rel(urn):
    return {"type": "Relationship", "object": urn}


def _legacy_norm(parcel_urn, day, ndvi):
    return {"id": f"urn:ngsi-ld:EOProduct:t:{parcel_urn.rsplit(':', 1)[-1]}:{day}", "type": "EOProduct",
            "refAgriParcel": _rel(parcel_urn), "sensingDate": _prop(day), "ndvi": _prop(ndvi)}


def _sdm_norm(parcel_urn, day, ndvi):
    pid = parcel_urn.rsplit(":", 1)[-1]
    return {"id": f"urn:ngsi-ld:EOSatelliteImagery:t:parcel:{pid}:s2-indices:{day}", "type": "EOSatelliteImagery",
            "hasAgriParcel": _rel(parcel_urn), "sensingDate": _prop(f"{day}T10:56:21Z"),
            "analytics": _prop([{"name": "ndvi", "value": f"{ndvi:.6f}"}, {"name": "pixelCount", "value": "900"}])}


@pytest.mark.asyncio
async def test_same_parcel_id_in_two_tenants_never_mixes():
    fakes = {"tenant-a": FakeOrion([_legacy_norm(PARCEL_URN, "2026-06-01", 0.3)]),
             "tenant-b": FakeOrion([_legacy_norm(PARCEL_URN, "2026-06-01", 0.8)])}
    with patch("nkz_platform_sdk.orion.OrionClient", side_effect=lambda tenant, **kw: fakes[tenant]):
        a = await eo_reader.observations("tenant-a", parcel_id="p1")
        b = await eo_reader.observations("tenant-b", parcel_id="p1")
    assert [o.values["ndvi"] for o in a] == [0.3] and [o.values["ndvi"] for o in b] == [0.8]


@pytest.mark.asyncio
async def test_an_expired_reading_is_read_again(monkeypatch):
    fo = FakeOrion([_legacy_norm(PARCEL_URN, "2026-06-01", 0.3)])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        await eo_reader.observations("acme", parcel_id="p1")
        monkeypatch.setattr(eo_reader, "_CACHE_TTL_S", -1.0)
        eo_reader.clear_cache()
        await eo_reader.observations("acme", parcel_id="p1")  # stored already expired
        await eo_reader.observations("acme", parcel_id="p1")
    assert len(fo.queries) == 6  # three reads of two queries each


@pytest.mark.asyncio
async def test_incomplete_read_is_raised_and_not_cached(monkeypatch):
    from nkz_platform_sdk import EOReadIncomplete

    calls = []

    async def fetch(client, **kw):
        calls.append(kw)
        if len(calls) == 1:
            raise EOReadIncomplete("EOProduct: more than 10000 entities")
        return []

    monkeypatch.setattr(eo_reader, "fetch_eo_observations", fetch)
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([])):
        with pytest.raises(EOReadIncomplete):
            await eo_reader.observations("acme", parcel_id="p1")
        assert await eo_reader.observations("acme", parcel_id="p1") == []
    assert len(calls) == 2
    assert calls[0]["names"] == eo_reader.USED_NAMES  # only the values crop-health reads are kept


@pytest.mark.asyncio
async def test_same_day_in_both_shapes_keeps_the_sdm_one():
    fo = FakeOrion([_legacy_norm(PARCEL_URN, "2026-06-01", 0.3), _sdm_norm(PARCEL_URN, "2026-06-01", 0.7)])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        obs = await eo_reader.observations("acme", parcel_id="p1")
    o = eo_reader.newest(obs, families=eo_reader.NDVI_FAMILIES, require={eo_reader.NDVI})
    assert len(obs) == 1 and o.shape == "sdm" and o.values["ndvi"] == 0.7


@pytest.mark.asyncio
async def test_a_cancelled_caller_does_not_leave_a_stale_reading():
    gate = asyncio.Event()

    class Slow(FakeOrion):
        async def query_entities(self, **kw):
            await gate.wait()
            return await super().query_entities(**kw)

    fo = Slow([_legacy_norm(PARCEL_URN, "2026-06-01", 0.3)])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        waiter = asyncio.ensure_future(eo_reader.observations("acme", parcel_id="p1"))
        await asyncio.sleep(0)
        waiter.cancel()
        gate.set()
        await asyncio.sleep(0.05)  # the read finishes with nobody waiting
        assert not eo_reader._inflight
        assert [o.values["ndvi"] for o in await eo_reader.observations("acme", parcel_id="p1")] == [0.3]
    assert len(fo.queries) == 2  # settled into the cache, not read again


def test_pick_refuses_names_crop_health_does_not_read():
    with pytest.raises(ValueError):
        eo_reader.pick([], families={"s2-composite"}, require={"ndvi"})
    with pytest.raises(ValueError):
        eo_reader.pick([], families=eo_reader.NDVI_FAMILIES, require={"NDVI"})
    with pytest.raises(TypeError):
        eo_reader.pick([], families=eo_reader.NDVI_FAMILIES, require="ndvi")


@pytest.mark.asyncio
async def test_expired_entries_are_purged_and_the_cache_is_capped(monkeypatch):
    monkeypatch.setattr(eo_reader, "_CACHE_MAX", 3)
    fo = FakeOrion([])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        for i in range(5):
            await eo_reader.observations("acme", parcel_id=f"p{i}")
        assert [k[1] for k in eo_reader._cache] == [eo_reader.parcel_urn(f"p{i}") for i in (2, 3, 4)]
        for key in list(eo_reader._cache):  # all of them expire
            eo_reader._cache[key] = (0.0, eo_reader._cache[key][1])
        await eo_reader.observations("acme", parcel_id="p9")
    assert list(eo_reader._cache) == [("acme", eo_reader.parcel_urn("p9"))]


@pytest.mark.asyncio
async def test_a_read_started_before_clear_cache_is_not_stored():
    gate = asyncio.Event()

    class Slow(FakeOrion):
        async def query_entities(self, **kw):
            await gate.wait()
            return await super().query_entities(**kw)

    with patch("nkz_platform_sdk.orion.OrionClient", return_value=Slow([])):
        reader = asyncio.ensure_future(eo_reader.observations("acme", parcel_id="p1"))
        await asyncio.sleep(0)
        eo_reader.clear_cache()
        gate.set()
        await reader
    assert not eo_reader._cache
