"""Per-zone soil water balance: own state per zone, area-weighted parcel state, zone probes."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas import SoilProperties
from app.services import pipeline
from app.services.daily_balance import advance_daily_balance
from app.services.redis_state import ParcelReading, RedisState
from app.services.zone_inputs import ZoneInputs
from app.services.zonation import Zone

SOIL = SoilProperties(field_capacity=0.27, wilting_point=0.12)
ROOT = 600.0
TODAY = date(2026, 10, 24)
NOW_DT = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
NOW_TS = NOW_DT.timestamp()
TENANT = "tenant-a"
PARCEL = "p-1"
_ZA = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
_ZB = {"type": "Polygon", "coordinates": [[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]]}


class ZoneFakeRedis:
    """In-memory swd store keyed like the real one, with probe readings."""

    def __init__(self, readings=None):
        self.store = {}
        self.readings = readings or []
        self.locks = set()

    async def get_balance_state(self, tenant_id, parcel_id, zone_id=None):
        return self.store.get(RedisState.balance_key(tenant_id, parcel_id, zone_id))

    async def set_balance_state(self, tenant_id, parcel_id, day, sw_mm, zone_id=None, **extras):
        self.store[RedisState.balance_key(tenant_id, parcel_id, zone_id)] = {
            "date": day, "sw_mm": sw_mm, **{k: v for k, v in extras.items() if v is not None},
        }
        return True

    async def try_lock(self, key, ttl_s):
        self.locks.add(key)
        return True

    async def unlock(self, key):
        return None

    async def get_parcel_readings(self, tenant_id, parcel_id, context, metric, max_age_s, now_ts):
        return list(self.readings) if metric == "soilMoisture" else []


async def _fetch(tenant_id, parcel_id, start, end):
    out, d = {}, start
    while d <= end:
        out[d.isoformat()] = (0.0, 3.0)
        d += timedelta(days=1)
    return out


@pytest.fixture(autouse=True)
def _patch_fetch(monkeypatch):
    async def _irrigation(tenant_id, parcel_id, start, end):
        return {}

    monkeypatch.setattr(pipeline, "_fetch_daily_water", _fetch)
    monkeypatch.setattr(pipeline, "_fetch_irrigation", _irrigation)


def _rows(eto, days=5):
    return [
        {"date": (TODAY - timedelta(days=days - i)).isoformat(), "eto": eto}
        for i in range(days)
    ]


def _zones_and_inputs(eto_a=2.0, eto_b=4.0, version_a="aaaaaaaa", devices_a=(), devices_b=()):
    za = Zone("zA", _ZA, zone_version=version_a, area_ha=3.0)
    zb = Zone("zB", _ZB, zone_version="bbbbbbbb", area_ha=1.0)
    inputs = {
        "zA": ZoneInputs(zone=za, weather={}, weather_daily=_rows(eto_a), sensors={},
                         fidelity={"balance": "parcel_inherited"}, devices=list(devices_a)),
        "zB": ZoneInputs(zone=zb, weather={}, weather_daily=_rows(eto_b), sensors={},
                         fidelity={"balance": "parcel_inherited"}, devices=list(devices_b)),
    }
    return [za, zb], inputs


def _crop_ctx():
    return {"phenology": None, "soil": SOIL, "root_depth_mm": ROOT, "now": NOW_DT}


async def _run(redis, zones, inputs):
    return await pipeline._scheduled_zone_balances(
        f"urn:ngsi-ld:AgriParcel:{TENANT}:{PARCEL}", PARCEL, TENANT, zones, inputs, _crop_ctx(),
        redis_state=redis, depletion_p=0.5, now_ts=NOW_TS,
    )


@pytest.mark.asyncio
async def test_zones_with_own_et0_diverge_and_parcel_is_weighted_mean():
    redis = ZoneFakeRedis()
    zones, inputs = _zones_and_inputs()
    # Seed both zones on the same state 5 days back so only the ET0 differs.
    for zid in ("zA", "zB"):
        await redis.set_balance_state(
            TENANT, PARCEL, "2026-10-18", 60.0, zone_id=zid, zone_version=inputs[zid].zone.zone_version,
            root_depth_mm=ROOT,
        )
    out = await _run(redis, zones, inputs)
    assert out["zA"].sw_mm > out["zB"].sw_mm
    parcel = redis.store[f"swd:{TENANT}:{PARCEL}"]
    assert parcel["source"] == "zones_weighted"
    assert parcel["date"] == "2026-10-23"
    assert parcel["sw_mm"] == pytest.approx(0.75 * out["zA"].sw_mm + 0.25 * out["zB"].sw_mm, abs=1e-3)
    assert "deficit_mm" not in parcel and "raw_mm" not in parcel
    assert inputs["zA"].fidelity["balance"] == "zone_specific"


@pytest.mark.asyncio
async def test_zone_without_own_data_is_parcel_inherited():
    redis = ZoneFakeRedis()
    zones, inputs = _zones_and_inputs()
    inputs["zA"].weather_daily = []
    await _run(redis, zones, inputs)
    assert inputs["zA"].fidelity["balance"] == "parcel_inherited"
    assert inputs["zB"].fidelity["balance"] == "zone_specific"


@pytest.mark.asyncio
async def test_zone_fc_wp_override_the_parcel_soil():
    redis = ZoneFakeRedis()
    zones, inputs = _zones_and_inputs(eto_a=3.0, eto_b=3.0)
    inputs["zB"].soil = {"fieldCapacity": 0.35, "wiltingPoint": 0.12}
    out = await _run(redis, zones, inputs)
    assert out["zB"].awc_mm > out["zA"].awc_mm


@pytest.mark.asyncio
async def test_zone_version_change_restarts_from_parcel_state(caplog):
    redis = ZoneFakeRedis()
    await redis.set_balance_state(TENANT, PARCEL, "2026-10-22", 77.0, root_depth_mm=ROOT)
    await redis.set_balance_state(
        TENANT, PARCEL, "2026-10-23", 10.0, zone_id="zA", zone_version="aaaaaaaa", root_depth_mm=ROOT
    )

    async def fetch(tenant_id, parcel_id, start, end):
        fetch.start = start
        return await _fetch(tenant_id, parcel_id, start, end)

    with caplog.at_level("INFO"):
        res = await advance_daily_balance(
            redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
            today=TODAY, fetch=fetch, zone_id="zA", zone_version="bbbbbbbb",
        )
    assert fetch.start == date(2026, 10, 23)  # replay starts the day after the parcel state
    assert res.sw_mm > 50.0  # from 77, not from the old zone's 10
    assert redis.store[f"swd:{TENANT}:{PARCEL}:zA"]["zone_version"] == "bbbbbbbb"
    assert "zone_version_changed" in caplog.text and "zA" in caplog.text


@pytest.mark.asyncio
async def test_same_zone_version_keeps_own_state():
    redis = ZoneFakeRedis()
    await redis.set_balance_state(TENANT, PARCEL, "2026-10-22", 77.0, root_depth_mm=ROOT)
    await redis.set_balance_state(
        TENANT, PARCEL, "2026-10-23", 10.0, zone_id="zA", zone_version="aaaaaaaa", root_depth_mm=ROOT
    )
    res = await advance_daily_balance(
        redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
        today=TODAY, fetch=_fetch, zone_id="zA", zone_version="aaaaaaaa",
    )
    assert res.sw_mm == pytest.approx(10.0, abs=0.01)  # state already at yesterday: nothing to step


@pytest.mark.asyncio
async def test_probe_in_zone_a_changes_only_zone_a():
    probe = ParcelReading(device_id="dev-1", ts=NOW_TS - 60, value=15.0, unit_code="P1")
    base = ZoneFakeRedis()
    zones, inputs = _zones_and_inputs()
    ref = await _run(base, zones, inputs)

    redis = ZoneFakeRedis(readings=[probe])
    zones, inputs = _zones_and_inputs(devices_a=[{"device_id": "dev-1", "lon": 0.5, "lat": 0.5}])
    out = await _run(redis, zones, inputs)
    assert out["zA"].sw_mm != pytest.approx(ref["zA"].sw_mm, abs=0.01)
    assert out["zB"].sw_mm == pytest.approx(ref["zB"].sw_mm)
    assert inputs["zA"].fidelity["balance"] == "iot_sensor"
    assert inputs["zB"].fidelity["balance"] == "zone_specific"
    # The probe became zone A's anchor.
    assert redis.store[f"swd:{TENANT}:{PARCEL}:zA"]["anchor_sw_mm"] == pytest.approx(out["zA"].sw_mm)


@pytest.mark.asyncio
async def test_unlocated_probe_corrects_every_zone_and_the_parcel_state():
    probe = ParcelReading(device_id="dev-nolocation", ts=NOW_TS - 60, value=15.0, unit_code="P1")
    ref_redis = ZoneFakeRedis()
    zones, inputs = _zones_and_inputs()
    ref = await _run(ref_redis, zones, inputs)

    redis = ZoneFakeRedis(readings=[probe])
    zones, inputs = _zones_and_inputs()
    out = await _run(redis, zones, inputs)
    for zid in ("zA", "zB"):
        assert out[zid].sw_mm != pytest.approx(ref[zid].sw_mm, abs=0.01)
        assert redis.store[f"swd:{TENANT}:{PARCEL}:{zid}"]["anchor_sw_mm"] == pytest.approx(out[zid].sw_mm)
        assert inputs[zid].fidelity["balance"] == "iot_sensor"
    parcel = redis.store[f"swd:{TENANT}:{PARCEL}"]
    assert parcel["sw_mm"] == pytest.approx(0.75 * out["zA"].sw_mm + 0.25 * out["zB"].sw_mm, abs=1e-3)


@pytest.mark.asyncio
async def test_zone_version_change_without_parcel_state_starts_fresh(caplog):
    redis = ZoneFakeRedis()
    await redis.set_balance_state(
        TENANT, PARCEL, "2026-10-23", 10.0, zone_id="zA", zone_version="aaaaaaaa", root_depth_mm=ROOT
    )

    async def fetch(tenant_id, parcel_id, start, end):
        fetch.start = start
        return await _fetch(tenant_id, parcel_id, start, end)

    with caplog.at_level("INFO"):
        await advance_daily_balance(
            redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
            today=TODAY, fetch=fetch, zone_id="zA", zone_version="bbbbbbbb",
        )
    assert fetch.start == date(2026, 9, 24)  # spin-up, as a zone with no state
    assert "fallback=fresh" in caplog.text and "zone_version_changed" in caplog.text


@pytest.mark.asyncio
async def test_zone_et0_overrides_parcel_et0_on_shared_days():
    async def run(eto_daily):
        redis = ZoneFakeRedis()
        await redis.set_balance_state(TENANT, PARCEL, "2026-10-20", 60.0, zone_id="zA",
                                      zone_version="aaaaaaaa", root_depth_mm=ROOT)
        return await advance_daily_balance(
            redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=0.5, kc=1.0,
            today=TODAY, fetch=_fetch, zone_id="zA", zone_version="aaaaaaaa", eto_daily=eto_daily,
        )

    base = await run(None)  # parcel ET0 3 mm/day
    hot = await run({date(2026, 10, 21): 6.0})
    assert hot.sw_mm < base.sw_mm


def test_zone_eto_daily_skips_bad_rows():
    rows = [{"date": "2026-10-20", "eto": 2.5}, {"date": "2026-10-21", "eto": None},
            {"date": "bad", "eto": 1.0}, {"date": "2026-10-22"}]
    assert pipeline._zone_eto_daily(rows) == {date(2026, 10, 20): 2.5}
