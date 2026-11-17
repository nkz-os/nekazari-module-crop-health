"""resolve_zones: one Zone per level of the current multidate zoning."""
import pytest

from app.services.zonation import fetch_terrain_units, is_whole_parcel, resolve_zones

PARCEL = "urn:ngsi-ld:AgriParcel:p1"
GEOM = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
RUN = "abcdef12" + "0" * 24


def _square(x0, y0, x1, y1):
    return [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]


def _amz(level, rank, area, run=RUN, method="vegetationIndexMultiDate", geom=GEOM, date="2026-11-17T12:00:00Z", **extra):
    row = {
        "id": f"urn:ngsi-ld:AgriManagementZone:p1:{run[:8]}:L{rank}",
        "type": "AgriManagementZone",
        "areaHa": area,
        "zoneId": rank,
        "zoneName": level,
        "zoneRank": rank,
        "dateZoned": {"@type": "DateTime", "@value": date},
        "zoningRunId": run,
        "zoningMethod": method,
        "refAgriParcel": PARCEL,
        "location": geom,
    }
    if level is not None:
        row["zoneLevel"] = level
    row.update(extra)
    return row


class _FakeOrion:
    def __init__(self, by_type):
        self.by_type = by_type
        self.calls = []

    async def query_entities(self, **kw):
        self.calls.append(kw)
        return self.by_type.get(kw["type"], [])

    async def close(self):
        pass


def _patch(monkeypatch, by_type):
    fake = _FakeOrion(by_type)
    monkeypatch.setattr("app.services.zonation._orion", lambda t: fake)
    return fake


@pytest.mark.asyncio
async def test_resolve_zones_current_multidate(monkeypatch):
    fake = _patch(monkeypatch, {"AgriManagementZone": [_amz("medium", 2, 7.93), _amz("high", 1, 0.95)]})
    zones = await resolve_zones(PARCEL, "acme", GEOM)
    assert [(z.zone_id, z.zone_rank, z.zone_version[:8]) for z in zones] == [("high", 1, "abcdef12"), ("medium", 2, "abcdef12")]
    assert zones[0].urn.startswith("urn:ngsi-ld:AgriManagementZone:")
    assert zones[0].zone_level == "high" and zones[0].zone_type == "management"
    assert zones[0].area_ha == 0.95
    assert fake.calls[0]["type"] == "AgriManagementZone"


@pytest.mark.asyncio
async def test_resolve_zones_reads_nkz_prefixed_forms(monkeypatch):
    row = _amz("high", 1, 1.0)
    row["https://nkz-os.org/ns/zoneLevel"] = row.pop("zoneLevel")
    row["nkz:areaHa"] = row.pop("areaHa")
    _patch(monkeypatch, {"AgriManagementZone": [row]})
    zones = await resolve_zones(PARCEL, "acme", GEOM)
    assert [(z.zone_id, z.area_ha) for z in zones] == [("high", 1.0)]


@pytest.mark.asyncio
async def test_resolve_zones_uses_most_recent_run(monkeypatch):
    old = [_amz("high", 1, 1.0, run="11111111" + "0" * 24, date="2026-10-01T00:00:00Z")]
    new = [_amz("low", 3, 2.0, date="2026-11-17T00:00:00Z")]
    _patch(monkeypatch, {"AgriManagementZone": old + new})
    zones = await resolve_zones(PARCEL, "acme", GEOM)
    assert [z.zone_id for z in zones] == ["low"]


@pytest.mark.asyncio
async def test_resolve_zones_ignores_non_multidate(monkeypatch):
    single = [_amz(None, 1, 5.0, method="vegetationIndex")]
    _patch(monkeypatch, {"AgriManagementZone": single})
    assert is_whole_parcel(await resolve_zones(PARCEL, "acme", GEOM))
    manual = [_amz("high", 1, 5.0, method="manual")]
    _patch(monkeypatch, {"AgriManagementZone": manual})
    assert is_whole_parcel(await resolve_zones(PARCEL, "acme", GEOM))


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [_amz("high", 1, 1.0), _amz("high", 2, 2.0)],
    [_amz("high", 1, 1.0), _amz(None, 2, 2.0)],
    [_amz("high", 1, 1.0), _amz("bogus", 2, 2.0)],
])
async def test_resolve_zones_whole_parcel_when_level_missing_or_duplicated(monkeypatch, rows):
    _patch(monkeypatch, {"AgriManagementZone": rows})
    assert is_whole_parcel(await resolve_zones(PARCEL, "acme", GEOM))


@pytest.mark.asyncio
async def test_resolve_zones_ignores_terrain_units(monkeypatch):
    unit = {"id": "urn:ngsi-ld:AgriParcelZone:acme:p1:z1", "zoneType": "management", "location": GEOM, "centroid": [0.5, 0.5]}
    _patch(monkeypatch, {"AgriParcelZone": [unit]})
    assert is_whole_parcel(await resolve_zones(PARCEL, "acme", GEOM))


@pytest.mark.asyncio
async def test_resolve_zones_whole_parcel_on_orion_error(monkeypatch):
    class Boom(_FakeOrion):
        async def query_entities(self, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr("app.services.zonation._orion", lambda t: Boom({}))
    assert is_whole_parcel(await resolve_zones(PARCEL, "acme", GEOM))


@pytest.mark.asyncio
async def test_resolve_zones_no_part_limit(monkeypatch):
    many = {"type": "MultiPolygon", "coordinates": [[_square(i, 0, i + 0.5, 0.5)] for i in range(6)]}
    holed = {"type": "Polygon", "coordinates": [_square(0, 0, 10, 10), _square(2, 2, 3, 3)]}
    _patch(monkeypatch, {"AgriManagementZone": [_amz("high", 1, 1.0, geom=many), _amz("medium", 2, 2.0, geom=holed)]})
    zones = await resolve_zones(PARCEL, "acme", GEOM)
    assert [z.zone_id for z in zones] == ["high", "medium"]
    assert len(zones[0].geometry["coordinates"]) == 6
    assert len(zones[1].geometry["coordinates"]) == 2


@pytest.mark.asyncio
async def test_fetch_terrain_units_accepts_management_and_terrain_excludes_hydrology(monkeypatch):
    def unit(zid, **kw):
        return {"id": f"urn:ngsi-ld:AgriParcelZone:acme:p1:{zid}", "zoneId": zid, "location": GEOM, **kw}

    rows = [
        unit("m", zoneType="management", tMin=2.0),
        unit("t", zoneType="terrain", tMin=3.0),
        unit("h", zoneType="hydrology", centroid=[0.5, 0.5]),
        unit("twi", twiMean=8.0, centroid=[0.5, 0.5]),
        unit("heur", centroid=[0.5, 0.5]),
        unit("plain"),
    ]
    _patch(monkeypatch, {"AgriParcelZone": rows})
    units = await fetch_terrain_units(PARCEL, "acme")
    assert [u.zone_id for u in units] == ["heur", "m", "t"]
    assert {u.zone_id: u.t_min for u in units}["t"] == 3.0


@pytest.mark.asyncio
async def test_fetch_terrain_units_empty_no_whole_parcel_fallback(monkeypatch):
    _patch(monkeypatch, {})
    assert await fetch_terrain_units(PARCEL, "acme") == []
