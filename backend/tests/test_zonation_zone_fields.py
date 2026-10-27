from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import zonation
from app.services.zonation import Zone, resolve_zones, zone_weights

POLY = {"type": "Polygon", "coordinates": [[[-2, 42], [-2, 42.1], [-1.9, 42.1], [-2, 42]]]}
NS = "https://nkz-os.org/ns/"
PARCEL_GEOM = POLY


def _row(prefix, zid="z1", **extra):
    row = {"id": f"urn:ngsi-ld:AgriParcelZone:acme:p1:{zid}", "location": POLY,
           prefix + "zoneId": zid, prefix + "zoneType": "management",
           prefix + "zoneVersion": "v3", prefix + "zoneRank": 2,
           prefix + "areaHa": 1.5, prefix + "pixelCount": 150,
           prefix + "solarRadiationWm2": 210.5, prefix + "frostRisk": 0.2,
           prefix + "sensorDistanceM": 340.0,
           "tMin": 3.1, "tMax": 17.4, "eto": 2.8,
           "dateObserved": "2026-10-26T00:00:00Z"}
    row.update(extra)
    return row


async def _resolve(rows):
    client = AsyncMock()
    client.query_entities.return_value = rows
    with patch.object(zonation, "_orion", return_value=client):
        return await resolve_zones("p1", "acme", PARCEL_GEOM)


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [NS, "nkz:"])
async def test_full_row_fields_same_in_both_spellings(prefix):
    (z,) = await _resolve([_row(prefix)])
    assert z.zone_type == "management" and z.zone_version == "v3" and z.zone_rank == 2
    assert z.area_ha == 1.5 and z.pixel_count == 150
    assert (z.t_min, z.t_max, z.eto) == (3.1, 17.4, 2.8)
    assert z.solar_radiation_wm2 == 210.5 and z.frost_risk == 0.2 and z.sensor_distance_m == 340.0
    assert z.observed_at == datetime(2026, 10, 26, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_date_observed_typed_value_and_unparsable():
    (z,) = await _resolve([_row("nkz:", dateObserved={"@type": "DateTime", "@value": "2026-10-26T05:00:00Z"})])
    assert z.observed_at == datetime(2026, 10, 26, 5, tzinfo=timezone.utc)
    (z,) = await _resolve([_row("nkz:", dateObserved="garbage")])
    assert z.observed_at is None
    (z,) = await _resolve([_row("nkz:", dateObserved="2026-10-26T05:00:00")])
    assert z.observed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_legacy_row_still_passes_heuristic():
    row = {"id": "urn:ngsi-ld:AgriParcelZone:acme:p1:a", "location": POLY,
           "nkz:zoneId": "a", "nkz:centroid": [-1.95, 42.05]}
    (z,) = await _resolve([row])
    assert z.zone_id == "a" and z.zone_type is None and z.area_ha is None and z.observed_at is None


@pytest.mark.asyncio
async def test_hydrology_simple_polygon_excluded():
    (z,) = await _resolve([_row("nkz:", zoneType=None, **{"nkz:zoneType": "hydrology"})])
    assert z.zone_id == "parcel"


def test_weights_by_area():
    zs = [Zone("a", {}, area_ha=1), Zone("b", {}, area_ha=1), Zone("c", {}, area_ha=2)]
    assert zone_weights(zs) == pytest.approx({"a": 0.25, "b": 0.25, "c": 0.5}, abs=1e-9)


def test_weights_pixel_fallback_and_equal_and_empty():
    zs = [Zone("a", {}, pixel_count=100), Zone("b", {}, pixel_count=300)]
    assert zone_weights(zs) == pytest.approx({"a": 0.25, "b": 0.75}, abs=1e-9)
    zs = [Zone("a", {}, area_ha=1), Zone("b", {}), Zone("c", {})]
    assert zone_weights(zs) == pytest.approx({k: 1 / 3 for k in "abc"}, abs=1e-9)
    assert zone_weights([]) == {}
