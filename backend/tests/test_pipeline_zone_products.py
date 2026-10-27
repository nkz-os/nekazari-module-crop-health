"""Per-zone EOProduct readers: zone_specific within 20 days, else parcel_inherited."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import pipeline

PARCEL = "p1"
PARCEL_URN = "urn:ngsi-ld:AgriParcel:p1"
ZONE_URN = "urn:ngsi-ld:AgriParcelZone:acme:p1:z1"


def _day(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _match(entity: dict, q: str) -> bool:
    """Tiny NGSI-LD q evaluator: ``a=="v"`` terms joined by ``|`` (or) and ``;`` (and)."""
    def term(t: str) -> bool:
        t = t.strip().strip("()")
        if ">=" in t:
            attr, _, val = t.partition(">=")
            return str(entity.get(attr, "")) >= val
        attr, _, val = t.partition("==")
        val = val.strip('"')
        got = entity.get(attr)
        if isinstance(got, dict):
            got = got.get("object", got.get("value"))
        return got == val

    def group(g: str) -> bool:
        return any(term(t) for t in g.split("|"))

    return all(group(g) for g in q.split(";"))


class FakeOrion:
    """OrionClient stand-in that applies ``q`` to a fixed entity set."""

    def __init__(self, entities):
        self.entities = entities
        self.queries: list[str] = []

    async def query_entities(self, type=None, q=None, limit=100, **kw):
        self.queries.append(q)
        out = [e for e in self.entities if e.get("type") == type]
        if q:
            out = [e for e in out if _match(e, q)]
        return out[:limit]

    async def close(self):
        pass


def _parcel_eo(days_ago, ndvi):
    return {"id": f"urn:ngsi-ld:EOProduct:acme:p1:{_day(days_ago)}", "type": "EOProduct",
            "hasAgriParcel": PARCEL_URN, "sensingDate": _day(days_ago), "ndvi": ndvi}


def _zone_eo(days_ago, ndvi, **extra):
    return {"id": f"urn:ngsi-ld:EOProduct:acme:zone:p1:z1:{_day(days_ago)}", "type": "EOProduct",
            "hasAgriParcelZone": ZONE_URN, "sensingDate": _day(days_ago), "ndvi": ndvi, **extra}


def test_fake_orion_parcel_query_ignores_zone_only_products():
    """A hasAgriParcel query must not return products that only carry hasAgriParcelZone."""
    import asyncio
    fo = FakeOrion([_parcel_eo(3, 0.5), _zone_eo(3, 0.9)])
    got = asyncio.run(fo.query_entities(type="EOProduct", q=f'hasAgriParcel=="{PARCEL_URN}"'))
    assert [e["ndvi"] for e in got] == [0.5]
    got = asyncio.run(fo.query_entities(type="EOProduct", q=f'hasAgriParcelZone=="{ZONE_URN}"'))
    assert [e["ndvi"] for e in got] == [0.9]


async def _ndvi(fo, zone_urn):
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        return await pipeline._fetch_parcel_ndvi(PARCEL, "acme", zone_urn)


@pytest.mark.asyncio
async def test_zone_product_5_days_old_is_zone_specific():
    fo = FakeOrion([_parcel_eo(2, 0.40), _zone_eo(5, 0.61)])
    assert await _ndvi(fo, ZONE_URN) == (0.61, "zone_specific")
    since = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
    assert fo.queries[0] == f'hasAgriParcelZone=="{ZONE_URN}";sensingDate>={since}'


@pytest.mark.asyncio
async def test_zone_product_25_days_old_falls_back_to_parcel():
    fo = FakeOrion([_parcel_eo(2, 0.40), _zone_eo(25, 0.61)])
    assert await _ndvi(fo, ZONE_URN) == (0.40, "parcel_inherited")


@pytest.mark.asyncio
async def test_newest_zone_product_wins():
    fo = FakeOrion([_zone_eo(15, 0.50), _zone_eo(4, 0.70)])
    assert await _ndvi(fo, ZONE_URN) == (0.70, "zone_specific")


@pytest.mark.asyncio
async def test_no_zone_urn_is_parcel_query_and_ignores_zone_products():
    fo = FakeOrion([_zone_eo(1, 0.9), _parcel_eo(3, 0.5)])
    assert await _ndvi(fo, None) == (0.5, "parcel_inherited")


@pytest.mark.asyncio
async def test_nothing_is_unavailable():
    assert await _ndvi(FakeOrion([]), ZONE_URN) == (None, "unavailable")


@pytest.mark.asyncio
async def test_sar_zone_specific_and_fallback():
    zone_grd = {"id": "g", "type": "EOProduct", "hasAgriParcelZone": ZONE_URN, "productType": "GRD",
                "sensingDate": _day(3), "backscatterVV": -11.0, "backscatterVH": -18.0}
    parcel_grd = {"id": "h", "type": "EOProduct", "hasAgriParcel": PARCEL_URN, "productType": "GRD",
                  "sensingDate": _day(3), "backscatterVV": -9.0, "backscatterVH": -15.0}
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([zone_grd, parcel_grd])):
        assert await pipeline._fetch_parcel_sar(PARCEL, "acme", ZONE_URN) == ((-11.0, -18.0), "zone_specific")
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([parcel_grd])):
        assert await pipeline._fetch_parcel_sar(PARCEL, "acme", ZONE_URN) == ((-9.0, -15.0), "parcel_inherited")
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([])):
        assert await pipeline._fetch_parcel_sar(PARCEL, "acme", ZONE_URN) == (None, "unavailable")


@pytest.mark.asyncio
async def test_smi_falls_back_to_parcel_when_zone_has_none():
    zone = _zone_eo(2, 0.6)  # no sarMoisture
    parcel = {**_parcel_eo(3, 0.5), "sarMoisture": 0.33}
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([zone, parcel])):
        assert await pipeline._fetch_parcel_smi(PARCEL, "acme", ZONE_URN) == (0.33, "parcel_inherited")


@pytest.mark.asyncio
async def test_zone_vigor_indices_from_same_product():
    zone = _zone_eo(2, 0.6, evi={"type": "Property", "value": 0.4}, savi=0.3, gndvi=0.5, ndre=0.2)
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=FakeOrion([zone])):
        idx = await pipeline._fetch_zone_vigor_indices(PARCEL, "acme", ZONE_URN)
    assert idx == {"evi": 0.4, "savi": 0.3, "gndvi": 0.5, "ndre": 0.2}
