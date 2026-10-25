"""Per-parcel Redis state is scoped by tenant (and, for readings, sensor context)."""
import time

import pytest

from app.services.redis_state import RedisState
from tests.test_parcel_readings import FakeRedis


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def state():
    return RedisState(client=FakeRedis())


@pytest.mark.anyio
async def test_readings_scoped_by_tenant_and_context(state):
    now = time.time()
    await state.set_parcel_reading("acme", "p1", "under_panel", "soilMoisture", "d1", now - 5, 30.0, "P1")
    got = await state.get_parcel_readings("acme", "p1", "under_panel", "soilMoisture", 3600, now)
    assert [r.device_id for r in got] == ["d1"]
    assert await state.get_parcel_readings("other", "p1", "under_panel", "soilMoisture", 3600, now) == []
    assert await state.get_parcel_readings("acme", "p1", "open_field", "soilMoisture", 3600, now) == []


@pytest.mark.anyio
async def test_soil_water_scoped_by_tenant(state):
    await state.set_balance_state("acme", "p1", "2026-06-14", 42.0)
    assert await state.get_balance_state("acme", "p1") == {"date": "2026-06-14", "sw_mm": 42.0}
    assert await state.get_balance_state("other", "p1") is None


@pytest.mark.anyio
async def test_shade_scoped_by_tenant(state):
    await state.add_shade_sample("acme", "p1", "2026-06-15", 400, 1600, 100.0)
    assert await state.get_daily_shade("acme", "p1", "2026-06-15") is not None
    assert await state.get_daily_shade_ts("acme", "p1", "2026-06-15") == 100.0
    assert await state.get_daily_shade("other", "p1", "2026-06-15") is None
    assert await state.get_daily_shade_ts("other", "p1", "2026-06-15") is None
