"""Pipeline over the levels of the current zoning: crossed terrain weather, zone products, balance seed."""
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.schemas import SoilProperties
from app.services import pipeline
from app.services.daily_balance import advance_daily_balance
from app.services.zonation import Zone, point_in_polygon, sensors_in_zone
from tests.test_compute_assessment_zonal import _patch_crop_level, _no_orion_cleanup, _no_zone_soil_twi_calls  # noqa: F401
from tests.test_zone_balance import ZoneFakeRedis, _fetch, SOIL, ROOT, TODAY, TENANT, PARCEL

# ~100 m squares near 42 N
LAT0, LON0 = 42.0, -1.6
DLAT = 100 / 111320
DLON = 100 / (111320 * 0.7431)


def _rect(x0, y0, x1, y1):
    lo = lambda x: LON0 + x * DLON  # noqa: E731
    la = lambda y: LAT0 + y * DLAT  # noqa: E731
    return [[lo(x0), la(y0)], [lo(x0), la(y1)], [lo(x1), la(y1)], [lo(x1), la(y0)], [lo(x0), la(y0)]]


def _poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


AMZ = "urn:ngsi-ld:AgriManagementZone:p1:abcdef12:L"


def _level(level, rank, geom):
    return Zone(level, geom, urn=f"{AMZ}{rank}", zone_type="management", zone_version="run1",
                zone_rank=rank, area_ha=1.0, zone_level=level)


def _unit(uid, geom, t_min, t_max=20.0, eto=3.0):
    return Zone(uid, geom, t_min=t_min, t_max=t_max, eto=eto,
                observed_at=datetime.now(timezone.utc) - timedelta(hours=1), area_ha=1.0)


@pytest.mark.asyncio
async def test_compute_assessment_uses_current_zones_and_crossed_meteo(monkeypatch):
    _patch_crop_level(monkeypatch)
    published = []

    async def _pub(entity, tid):
        published.append(entity)
        return True

    zones = [_level("high", 1, _poly(_rect(0, 0, 0.5, 1))), _level("medium", 2, _poly(_rect(0.5, 0, 1, 1)))]
    units = [_unit("uW", _poly(_rect(0, 0, 0.5, 1)), t_min=2.0), _unit("uE", _poly(_rect(0.5, 0, 1, 1)), t_min=6.0)]

    async def _zones(pid, tid, geom):
        return zones

    async def _units(pid, tid):
        return units

    async def _no_sensors(pid, tid):
        return []

    async def _daily(*a, **k):
        return {"uW": [{"date": "2026-05-01", "tMin": 2.0, "tMax": 20.0, "eto": 3.0}],
                "uE": [{"date": "2026-05-01", "tMin": 6.0, "tMax": 20.0, "eto": 3.0}]}

    ctxs = {}
    real = pipeline._assess_zone

    async def _spy(zone, *args, **kwargs):
        ctxs[zone.zone_id] = kwargs.get("zone_ctx")
        return await real(zone, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "fetch_terrain_units", _units)
    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", _no_sensors)
    monkeypatch.setattr(pipeline, "_fetch_zone_daily", _daily)
    monkeypatch.setattr(pipeline, "_assess_zone", _spy)

    await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:p1", "acme")
    zone_entities = [e for e in published if e["type"] == "CropHealthZoneAssessment"]
    assert len(zone_entities) == 2
    assert {e["hasAgriParcelZone"]["object"] for e in zone_entities} == {f"{AMZ}1", f"{AMZ}2"}
    # each level took the weather of the unit that covers it; frost uses the coldest unit
    assert ctxs["high"]["air_temp_min_24h"] == pytest.approx(2.0, abs=0.1)
    assert ctxs["medium"]["air_temp_min_24h"] == pytest.approx(6.0, abs=0.1)
    assert ctxs["high"]["air_temp_c"] == pytest.approx(11.0, abs=0.1)


def test_zone_meteo_ctx_frost_uses_coldest_unit():
    from app.services.zone_inputs import zone_meteo_ctx
    now = datetime.now(timezone.utc)
    z = Zone("high", {}, t_min=4.0, t_max=20.0, t_min_coldest=1.0, observed_at=now)
    assert zone_meteo_ctx(z, now)["air_temp_min_24h"] == 1.0
    z.t_min_coldest = None
    assert zone_meteo_ctx(z, now)["air_temp_min_24h"] == 4.0


@pytest.mark.asyncio
async def test_gather_zone_inputs_crosses_daily_and_skips_uncovered_zone():
    from app.services.zone_inputs import gather_zone_inputs
    za, zb = _level("high", 1, {}), _level("medium", 2, {})

    async def _daily(*a):
        return {"u1": [{"date": "2026-05-01", "tMin": 2.0, "tMax": 10.0, "eto": 1.0}],
                "u2": [{"date": "2026-05-01", "tMin": 4.0, "tMax": 20.0, "eto": 3.0}]}

    async def _none(*a, **k):
        return []

    async def _empty(*a, **k):
        return {}

    out = await gather_zone_inputs(
        "urn:x", "p1", "acme", [za, zb], date(2026, 5, 1), datetime(2026, 5, 2, tzinfo=timezone.utc),
        fetch_daily=_daily, gather_sensors=_none, fetch_soil=_empty, fetch_twi=_empty,
        fractions_by_zone={"high": {"u1": 0.5, "u2": 0.5}},
    )
    assert out["high"].weather_daily == [{"date": "2026-05-01", "tMin": 3.0, "tMax": 15.0, "eto": 2.0}]
    assert out["medium"].weather_daily == []


@pytest.mark.asyncio
async def test_zone_product_query_uses_management_zone_relation():
    from tests.test_pipeline_zone_products import FakeOrion
    fo = FakeOrion([])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        await pipeline._fetch_parcel_ndvi("p1", "acme", f"{AMZ}1")
        await pipeline._fetch_ndvi_series("acme", "p1", f"{AMZ}1", date(2026, 5, 1))
        await pipeline._fetch_parcel_ndvi("p1", "acme", "urn:ngsi-ld:AgriParcelZone:acme:p1:z1")
    assert fo.queries[0].startswith('hasAgriManagementZone=="urn:ngsi-ld:AgriManagementZone:')
    # queries[1] is the parcel fallback of the first call
    assert fo.queries[2].startswith('hasAgriManagementZone=="urn:ngsi-ld:AgriManagementZone:')
    assert fo.queries[3].startswith('hasAgriParcelZone=="urn:ngsi-ld:AgriParcelZone:')


def test_sensor_in_hole_belongs_to_inner_zone():
    outer = _poly(_rect(0, 0, 1, 1), _rect(0.25, 0.25, 0.75, 0.75)[::-1])
    inner = _poly(_rect(0.25, 0.25, 0.75, 0.75))
    medium = _level("medium", 2, outer)
    high = _level("high", 1, inner)
    s = [{"device_id": "d1", "lon": LON0 + 0.5 * DLON, "lat": LAT0 + 0.5 * DLAT}]
    assert point_in_polygon(s[0]["lon"], s[0]["lat"], outer) is False
    assert sensors_in_zone(medium, s) == []
    assert sensors_in_zone(high, s) == s


@pytest.mark.asyncio
async def test_zone_without_state_seeds_from_parcel(caplog):
    redis = ZoneFakeRedis()
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    await redis.set_balance_state(TENANT, PARCEL, yesterday, 80.0, root_depth_mm=ROOT)

    async def fetch(tenant_id, parcel_id, start, end):
        fetch.start = start
        return await _fetch(tenant_id, parcel_id, start, end)

    with caplog.at_level("INFO"):
        res = await advance_daily_balance(
            redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
            today=TODAY, fetch=fetch, zone_id="high", zone_version="run1",
        )
    assert res.sw_mm == pytest.approx(80.0, abs=0.5)  # from the parcel's 80, no spin-up
    assert getattr(fetch, "start", None) != TODAY - timedelta(days=61)
    assert "reason=zone_state_missing" in caplog.text


@pytest.mark.asyncio
async def test_zone_version_change_seeds_from_parcel(caplog):
    redis = ZoneFakeRedis()
    await redis.set_balance_state(TENANT, PARCEL, "2026-10-22", 77.0, root_depth_mm=ROOT)
    await redis.set_balance_state(TENANT, PARCEL, "2026-10-23", 10.0, zone_id="high", zone_version="run0",
                                  root_depth_mm=ROOT)
    with caplog.at_level("INFO"):
        res = await advance_daily_balance(
            redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
            today=TODAY, fetch=_fetch, zone_id="high", zone_version="run1",
        )
    assert res.sw_mm > 50.0
    assert "reason=zone_version_changed" in caplog.text


def test_overlap_cost_on_small_zones_is_bounded():
    """A level with ~1,600 samples against several units: one crossing stays well under a second."""
    from app.services.terrain_meteo import apply_terrain_meteo, overlap_fractions
    zone = _poly(_rect(0, 0, 1, 1))
    units = [_unit(f"u{i}", _poly(_rect(i / 6, 0, (i + 1) / 6, 1)), t_min=float(i)) for i in range(6)]
    t0 = time.perf_counter()
    fr, covered, ha = overlap_fractions(zone, units)
    apply_terrain_meteo(_level("high", 1, zone), units, fr, covered, ha)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_sensor_triggered_zonal_assessment_uses_crossed_zone_weather(monkeypatch):
    """The sensor path crosses terrain weather too: each zone gets its own zone meteo context."""
    from tests.test_trigger_zonal import _Redis, _patch_trigger
    from app.schemas import MetricType

    zones = [_level("high", 1, _poly(_rect(0, 0, 0.5, 1))), _level("medium", 2, _poly(_rect(0.5, 0, 1, 1)))]
    units = [_unit("uW", _poly(_rect(0, 0, 0.5, 1)), t_min=2.0, t_max=10.0),
             _unit("uE", _poly(_rect(0.5, 0, 1, 1)), t_min=6.0, t_max=30.0)]
    calls, _ = _patch_trigger(monkeypatch, zones=zones, device_coords=(LON0 + 0.25 * DLON, LAT0 + 0.5 * DLAT))

    async def _units(pid, tid):
        return units

    seen = {}
    real = pipeline.resolve_meteo_context

    async def _spy(parcel_id, tenant_id, **kw):
        ctx = kw.get("zone_ctx")
        if ctx:
            seen[round(ctx["air_temp_c"])] = ctx["air_temp_min_24h"]
        return await real(parcel_id, tenant_id, **kw)

    monkeypatch.setattr(pipeline, "fetch_terrain_units", _units)
    monkeypatch.setattr(pipeline, "resolve_meteo_context", _spy)
    out = await pipeline.trigger(
        entity_id="urn:ngsi-ld:DeviceMeasurement:d1", metric_type=MetricType.LEAF_TEMPERATURE.value,
        redis_state=_Redis(), parcel_id="p1", tenant_id="t",
    )
    assert out is not None
    # high: mean (2+10)/2 = 6, coldest 2; medium: mean (6+30)/2 = 18, coldest 6
    assert seen == {6: pytest.approx(2.0, abs=0.1), 18: pytest.approx(6.0, abs=0.1)}
    by_zone = {c["zone_id"]: c["weather"].temp_air for c in calls}
    assert by_zone["high"] == pytest.approx(6.0, abs=0.1)
    assert by_zone["medium"] == pytest.approx(18.0, abs=0.1)


@pytest.mark.asyncio
async def test_sensor_path_keeps_parcel_weather_when_crossing_fails(monkeypatch):
    from tests.test_trigger_zonal import _Redis, _patch_trigger
    from app.schemas import MetricType

    zones = [_level("high", 1, _poly(_rect(0, 0, 0.5, 1))), _level("medium", 2, _poly(_rect(0.5, 0, 1, 1)))]
    calls, _ = _patch_trigger(monkeypatch, zones=zones, device_coords=(LON0, LAT0))

    async def _boom(pid, tid):
        raise RuntimeError("broker down")

    monkeypatch.setattr(pipeline, "fetch_terrain_units", _boom)
    out = await pipeline.trigger(
        entity_id="urn:ngsi-ld:DeviceMeasurement:d1", metric_type=MetricType.LEAF_TEMPERATURE.value,
        redis_state=_Redis(), parcel_id="p1", tenant_id="t",
    )
    assert out is not None
    assert {c["weather"].temp_air for c in calls} == {21.0}  # the parcel's weather-map value
