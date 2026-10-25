"""Soil water balance state: {date, sw_mm} per tenant and parcel."""
import pytest

from app.services.redis_state import RedisState
from tests.test_redis_json_lock import FakeRedis


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_balance_state_roundtrip():
    fake = FakeRedis()
    st = RedisState(client=fake)
    assert await st.set_balance_state("tenant-a", "p-1", "2026-10-20", 42.5)
    assert any("tenant-a" in key for key in fake.kv)
    assert await st.get_balance_state("tenant-a", "p-1") == {"date": "2026-10-20", "sw_mm": 42.5}


@pytest.mark.anyio
async def test_balance_state_absent_is_none():
    st = RedisState(client=FakeRedis())
    assert await st.get_balance_state("tenant-a", "p-1") is None


@pytest.mark.anyio
async def test_balance_state_keeps_the_day_flows():
    st = RedisState(client=FakeRedis())
    assert await st.set_balance_state(
        "tenant-a", "p-1", "2026-10-20", 42.5, precip_mm=3.0, etc_mm=2.4,
        actual_et_mm=2.0, deep_percolation_mm=0.5, root_depth_mm=800.0,
    )
    assert await st.get_balance_state("tenant-a", "p-1") == {
        "date": "2026-10-20", "sw_mm": 42.5, "precip_mm": 3.0, "etc_mm": 2.4,
        "actual_et_mm": 2.0, "deep_percolation_mm": 0.5, "root_depth_mm": 800.0,
    }


@pytest.mark.anyio
async def test_balance_state_keeps_anchor_fields():
    st = RedisState(client=FakeRedis())
    assert await st.set_balance_state(
        "tenant-a", "p-1", "2026-10-23", 42.5, root_depth_mm=600.0,
        anchor_date="2026-10-16", anchor_sw_mm=40.0, anchor_root_depth_mm=600.0,
    )
    assert await st.get_balance_state("tenant-a", "p-1") == {
        "date": "2026-10-23", "sw_mm": 42.5, "root_depth_mm": 600.0,
        "anchor_date": "2026-10-16", "anchor_sw_mm": 40.0, "anchor_root_depth_mm": 600.0,
    }
