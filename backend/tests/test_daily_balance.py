"""Daily soil water stepper and sensor correction (fake Redis, fake weather fetch)."""
from datetime import date

import pytest

from app.schemas import SoilProperties
from app.services import daily_balance
from app.services.daily_balance import (
    advance_daily_balance,
    balance_from_state,
    correct_balance_state,
    step_day,
)
from app.services.redis_state import ParcelReading, StoreError

SOIL = SoilProperties(field_capacity=0.27, wilting_point=0.12)
ROOT = 600.0
P = 0.5
TODAY = date(2026, 10, 24)
TENANT = "tenant-a"
PARCEL = "p-1"
NOW = 1_800_000_000.0


class FakeRedis:
    def __init__(self, state=None, lock=True, fail=False):
        self.state = state
        self.lock = lock
        self.fail = fail
        self.saved = []
        self.flows = []
        self.locked = []
        self.unlocked = []

    async def get_balance_state(self, tenant_id, parcel_id):
        if self.fail:
            raise StoreError("down")
        return self.state

    async def set_balance_state(self, tenant_id, parcel_id, day, sw_mm, precip_mm=None, etc_mm=None):
        self.saved.append((day, sw_mm))
        self.flows.append((precip_mm, etc_mm))
        return True

    async def try_lock(self, key, ttl_s):
        self.locked.append((key, ttl_s))
        return self.lock

    async def unlock(self, key):
        self.unlocked.append(key)


def make_fetch(data=None, result="ok"):
    calls = []

    async def fetch(tenant_id, parcel_id, start, end):
        calls.append((start, end))
        if result is None:
            return None
        out = {}
        d = start
        from datetime import timedelta

        while d <= end:
            out[d.isoformat()] = (1.0, 3.0)
            d += timedelta(days=1)
        out.update(data or {})
        return out

    fetch.calls = calls
    return fetch


async def advance(redis, fetch):
    return await advance_daily_balance(
        redis, TENANT, PARCEL, soil=SOIL, root_depth_mm=ROOT, depletion_p=P,
        kc=1.0, today=TODAY, fetch=fetch,
    )


def test_step_day_rain_raises_water():
    r = step_day(40.0, 10.0, 0.0, 1.0, SOIL, ROOT, P)
    assert r.sw_mm == pytest.approx(50.0)


def test_step_day_et_uses_kc():
    r = step_day(60.0, 0.0, 5.0, 0.8, SOIL, ROOT, P)
    assert r.etc_mm == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_spinup_steps_30_days_when_no_state():
    redis, fetch = FakeRedis(), make_fetch()
    res = await advance(redis, fetch)
    assert fetch.calls == [(date(2026, 9, 24), date(2026, 10, 23))]
    assert redis.saved[-1][0] == "2026-10-23"
    assert res is not None and res.soil_moisture_confidence != "low"
    assert redis.locked == [(f"swd-lock:{TENANT}:{PARCEL}", 120)]
    assert redis.unlocked == [f"swd-lock:{TENANT}:{PARCEL}"]


@pytest.mark.asyncio
async def test_resume_from_saved_day():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 50.0})
    fetch = make_fetch()
    await advance(redis, fetch)
    assert fetch.calls == [(date(2026, 10, 21), date(2026, 10, 23))]
    assert redis.saved[-1][0] == "2026-10-23"


@pytest.mark.asyncio
async def test_stops_at_first_missing_day():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 50.0})
    fetch = make_fetch({"2026-10-22": (1.0, None)})
    res = await advance(redis, fetch)
    assert redis.saved[-1][0] == "2026-10-21"
    assert len(redis.saved) == 1
    assert res.soil_moisture_confidence == "low"


@pytest.mark.asyncio
async def test_store_error_skips_without_spinup():
    redis, fetch = FakeRedis(fail=True), make_fetch()
    assert await advance(redis, fetch) is None
    assert redis.saved == []
    assert fetch.calls == []
    assert redis.unlocked


@pytest.mark.asyncio
async def test_lock_held_skips():
    redis, fetch = FakeRedis(lock=False), make_fetch()
    assert await advance(redis, fetch) is None
    assert fetch.calls == [] and redis.saved == []


@pytest.mark.asyncio
async def test_lock_unavailable_skips():
    redis, fetch = FakeRedis(lock=None), make_fetch()
    assert await advance(redis, fetch) is None
    assert fetch.calls == [] and redis.saved == []


@pytest.mark.asyncio
async def test_fetch_failure_keeps_state():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 50.0})
    res = await advance(redis, make_fetch(result=None))
    assert res.sw_mm == pytest.approx(50.0)
    assert res.soil_moisture_confidence == "low"
    assert redis.saved == []


@pytest.mark.asyncio
async def test_fetch_failure_without_state_returns_none():
    redis = FakeRedis()
    assert await advance(redis, make_fetch(result=None)) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_up_to_date_returns_state_balance():
    redis = FakeRedis(state={"date": "2026-10-23", "sw_mm": 55.0})
    fetch = make_fetch()
    res = await advance(redis, fetch)
    assert fetch.calls == [] and redis.saved == []
    assert res.sw_mm == pytest.approx(balance_from_state(55.0, SOIL, ROOT, P).sw_mm)


@pytest.mark.asyncio
async def test_first_day_missing_saves_nothing():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 50.0})
    res = await advance(redis, make_fetch({"2026-10-21": (None, 3.0)}))
    assert redis.saved == []
    assert res.soil_moisture_confidence == "low" and res.sw_mm == pytest.approx(50.0)


def reading(value=20.0):
    return ParcelReading(device_id="d-1", ts=NOW - 60, value=value, unit_code="P1")


@pytest.mark.asyncio
async def test_correction_keeps_date():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 30.0})
    sw = await correct_balance_state(redis, TENANT, PARCEL, [reading()], SOIL, ROOT, 90.0, NOW)
    assert sw == pytest.approx(48.0)
    assert redis.saved == [("2026-10-20", pytest.approx(48.0))]
    assert redis.unlocked


@pytest.mark.asyncio
async def test_correction_without_state_does_nothing():
    redis = FakeRedis()
    assert await correct_balance_state(redis, TENANT, PARCEL, [reading()], SOIL, ROOT, 90.0, NOW) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_correction_without_valid_readings_does_nothing():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 30.0})
    assert await correct_balance_state(redis, TENANT, PARCEL, [], SOIL, ROOT, 90.0, NOW) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_correction_lock_held_does_nothing():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 30.0}, lock=False)
    assert await correct_balance_state(redis, TENANT, PARCEL, [reading()], SOIL, ROOT, 90.0, NOW) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_stale_state_with_fetch_failure_returns_none():
    redis = FakeRedis(state={"date": "2026-09-01", "sw_mm": 50.0})
    assert await advance(redis, make_fetch(result=None)) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_stale_state_with_first_day_missing_returns_none():
    redis = FakeRedis(state={"date": "2026-09-01", "sw_mm": 50.0})
    assert await advance(redis, make_fetch({"2026-09-24": (None, 3.0)})) is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_step_saves_the_last_day_flows():
    redis = FakeRedis(state={"date": "2026-10-21", "sw_mm": 50.0})
    res = await advance(redis, make_fetch({"2026-10-23": (4.0, 2.0)}))
    assert redis.saved[-1][0] == "2026-10-23"
    assert redis.flows == [(pytest.approx(4.0), pytest.approx(2.0))]
    assert (res.inflow_mm, res.etc_mm) == (pytest.approx(4.0), pytest.approx(2.0))


@pytest.mark.asyncio
async def test_current_state_carries_its_stored_flows():
    redis = FakeRedis(state={"date": "2026-10-23", "sw_mm": 50.0, "precip_mm": 4.0, "etc_mm": 2.0})
    res = await advance(redis, make_fetch())
    assert res.day_flows_known
    assert (res.inflow_mm, res.etc_mm) == (4.0, 2.0)


@pytest.mark.asyncio
async def test_current_state_without_flows_marks_them_unknown():
    redis = FakeRedis(state={"date": "2026-10-23", "sw_mm": 50.0})
    res = await advance(redis, make_fetch())
    assert res.day_flows_known is False


def test_balance_from_state_flows():
    assert balance_from_state(50.0, SOIL, ROOT, P).day_flows_known is False
    r = balance_from_state(50.0, SOIL, ROOT, P, precip_mm=4.0, etc_mm=2.0)
    assert r.day_flows_known and (r.inflow_mm, r.etc_mm) == (4.0, 2.0)
    assert r.sw_mm == balance_from_state(50.0, SOIL, ROOT, P).sw_mm


@pytest.mark.asyncio
async def test_correction_keeps_the_stored_flows():
    redis = FakeRedis(state={"date": "2026-10-20", "sw_mm": 30.0, "precip_mm": 4.0, "etc_mm": 2.0})
    await correct_balance_state(redis, TENANT, PARCEL, [reading()], SOIL, ROOT, 90.0, NOW)
    assert redis.flows == [(4.0, 2.0)]
