"""Parcel point and irrigation regime for the cereal stage-table request."""
import asyncio

import pytest

from app.schemas import StageTable
from app.services import context_client, parcel_site

CAL = {"id": "aquacrop_calendar"}


class _Orion:
    entity: dict = {}
    crops: list = []
    entity_fail = False
    crop_fail = False
    delay = 0.0
    ctor_fail = False
    calls = 0

    def __init__(self, *a, **k):
        if self.ctor_fail:
            raise RuntimeError("bad client config")

    async def get_entity(self, *a, **k):
        _Orion.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.entity_fail:
            raise RuntimeError("down")
        return self.entity

    async def query_entities(self, **k):
        if self.crop_fail:
            raise RuntimeError("down")
        return self.crops

    async def close(self):
        return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    parcel_site._site_cache.clear()
    parcel_site._site_short.clear()
    for k, v in dict(entity={}, crops=[], entity_fail=False, crop_fail=False, delay=0.0,
                     ctor_fail=False, calls=0).items():
        setattr(_Orion, k, v)
    monkeypatch.setattr(parcel_site, "OrionClient", _Orion)
    yield
    parcel_site._site_cache.clear()
    parcel_site._site_short.clear()


@pytest.mark.parametrize("word,expected", [
    ("secano", "rainfed"), ("rainfed", "rainfed"), ("drip", "irrigated"), ("Regadío", "irrigated"),
    ("sin riego", "rainfed"), ("non-irrigated", "rainfed"), ("none", "rainfed"), ("", None),
    ("mixed", None), (None, None), ({"value": "sprinkler"}, "irrigated"),
])
def test_regime_word(word, expected):
    assert parcel_site.regime_word(word) == expected


@pytest.mark.asyncio
async def test_point_and_regime_from_parcel():
    _Orion.entity = {"location": {"type": "Point", "coordinates": [-1.6, 42.8]}, "irrigationSystemType": "drip"}
    site = await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert site == parcel_site.ParcelSite(lat=42.8, lon=-1.6, regime="irrigated")


@pytest.mark.asyncio
async def test_polygon_centroid_and_geoproperty_wrapper():
    ring = [[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]
    _Orion.entity = {"location": {"type": "GeoProperty", "value": {"type": "Polygon", "coordinates": [ring]}}}
    site = await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert site.lat is not None and site.lon is not None and site.regime is None


@pytest.mark.asyncio
async def test_crop_regime_wins_and_placeholder_is_skipped():
    _Orion.entity = {"location": {"type": "Point", "coordinates": [-1.6, 42.8]}, "irrigationSystemType": "drip"}
    _Orion.crops = [{"provenance": "placeholder", "irrigationRegime": "drip"}, {"irrigationRegime": "secano"}]
    assert (await parcel_site.resolve_parcel_site("p1", "tenant-a")).regime == "rainfed"


@pytest.mark.asyncio
async def test_complete_read_is_cached_long():
    _Orion.entity = {"location": {"type": "Point", "coordinates": [1.0, 2.0]}}
    await parcel_site.resolve_parcel_site("p1", "tenant-a")
    await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert _Orion.calls == 1 and "tenant-a:p1" in parcel_site._site_cache
    assert parcel_site._site_cache.ttl == 3600


@pytest.mark.asyncio
async def test_crop_read_error_is_short_cached_not_long():
    _Orion.entity = {"location": {"type": "Point", "coordinates": [1.0, 2.0]}, "irrigationSystemType": "drip"}
    _Orion.crop_fail = True
    site = await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert site.lat == 2.0  # what could be read is kept
    assert "tenant-a:p1" not in parcel_site._site_cache and "tenant-a:p1" in parcel_site._site_short
    assert parcel_site._site_short.ttl <= 60
    await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert _Orion.calls == 1  # the short negative cache absorbs the retry


@pytest.mark.asyncio
async def test_parcel_read_error_is_short_cached():
    _Orion.entity_fail = True
    site = await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert site == parcel_site.ParcelSite(None, None, None)
    assert "tenant-a:p1" in parcel_site._site_short and "tenant-a:p1" not in parcel_site._site_cache


@pytest.mark.asyncio
async def test_slow_broker_hits_the_site_timeout(monkeypatch):
    monkeypatch.setattr(parcel_site, "_TIMEOUT_S", 0.05)
    _Orion.delay = 1.0
    site = await parcel_site.resolve_parcel_site("p1", "tenant-a")
    assert site == parcel_site.ParcelSite(None, None, None)
    assert "tenant-a:p1" in parcel_site._site_short


@pytest.mark.asyncio
async def test_constructor_failure_degrades_to_no_site():
    _Orion.ctor_fail = True
    assert await parcel_site.resolve_parcel_site("p1", "tenant-a") == parcel_site.ParcelSite(None, None, None)


def _record(monkeypatch, tables):
    seen = []

    async def _stages(species, **kw):
        seen.append((species, kw))
        return tables.get(bool(kw), tables[False])

    monkeypatch.setattr(context_client, "get_phenology_stages", _stages)
    return seen


@pytest.mark.asyncio
async def test_other_crop_never_reads_the_parcel(monkeypatch):
    seen = _record(monkeypatch, {False: StageTable()})

    async def _boom(*a):
        raise AssertionError("site lookup must not run for other crops")

    monkeypatch.setattr(parcel_site, "resolve_parcel_site", _boom)
    t = await parcel_site.get_parcel_stage_table("Zea mays", "p1", "tenant-a")
    assert t.model is None and seen == [("Zea mays", {})]


@pytest.mark.asyncio
async def test_cereal_gets_site_aware_table(monkeypatch):
    plain = StageTable(model=CAL)
    sited = StageTable(model=CAL, calibration={"status": "calibrated"})
    seen = _record(monkeypatch, {False: plain, True: sited})
    _Orion.entity = {"location": {"type": "Point", "coordinates": [-1.6, 42.8]}, "irrigationRegime": "rainfed"}
    t = await parcel_site.get_parcel_stage_table("wheat", "p1", "tenant-a")
    assert t is sited
    assert seen == [("wheat", {}), ("wheat", {"lat": 42.8, "lon": -1.6, "irrigation": "rainfed"})]


@pytest.mark.asyncio
async def test_cereal_without_site_keeps_plain_calendar_table(monkeypatch):
    plain = StageTable(model=CAL)
    seen = _record(monkeypatch, {False: plain})
    _Orion.entity_fail = True
    t = await parcel_site.get_parcel_stage_table("wheat", "p1", "tenant-a")
    assert t is plain and seen == [("wheat", {})]


@pytest.mark.asyncio
async def test_site_request_falling_back_to_generic_keeps_plain_calendar(monkeypatch):
    plain = StageTable(model=CAL)
    _record(monkeypatch, {False: plain, True: StageTable()})
    _Orion.entity = {"location": {"type": "Point", "coordinates": [-1.6, 42.8]}}
    assert await parcel_site.get_parcel_stage_table("wheat", "p1", "tenant-a") is plain


def test_gdd_kwargs():
    assert parcel_site.gdd_kwargs(StageTable(gdd_method="aquacrop_m3")) == {"gdd_method": "aquacrop_m3"}
    assert parcel_site.gdd_kwargs(StageTable()) == {}
    assert parcel_site.gdd_kwargs({}) == {}
    assert parcel_site.gdd_kwargs(None) == {}


@pytest.mark.asyncio
async def test_degraded_species_table_is_passed_through(monkeypatch):
    """An empty or non-table answer for the species never raises and never reads the parcel."""
    from app.services import context_client, parcel_site

    async def _empty(species, **kw):
        return {}

    async def _no_site(*a, **k):
        raise AssertionError("parcel site must not be read")

    monkeypatch.setattr(context_client, "get_phenology_stages", _empty)
    monkeypatch.setattr(parcel_site, "resolve_parcel_site", _no_site)
    assert await parcel_site.get_parcel_stage_table("wheat", "urn:ngsi-ld:AgriParcel:p1", "tenant-a") == {}
