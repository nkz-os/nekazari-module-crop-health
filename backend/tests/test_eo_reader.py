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
