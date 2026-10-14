"""RedisState JSON + lock helpers: prefix, NX lock, degraded mode."""
import pytest

from app.services.redis_state import RedisState


class FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)

    async def exists(self, k):
        return int(k in self.kv)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_json_roundtrip_under_prefix():
    fake = FakeRedis()
    st = RedisState(client=fake)
    assert await st.set_json("k", {"a": 1}, 60)
    assert any(key.endswith("k") and key != "k" for key in fake.kv)
    assert await st.get_json("k") == {"a": 1}


@pytest.mark.anyio
async def test_lock_is_exclusive_until_unlocked():
    st = RedisState(client=FakeRedis())
    assert await st.try_lock("l", 300) is True
    assert await st.try_lock("l", 300) is False
    assert await st.is_locked("l")
    await st.unlock("l")
    assert not await st.is_locked("l")


@pytest.mark.anyio
async def test_degraded_mode():
    st = RedisState()
    from app.services.redis_state import StoreError
    assert st.available is False
    with pytest.raises(StoreError):
        await st.get_json("k")
    assert await st.set_json("k", {}, 1) is False
    assert await st.try_lock("l", 1) is None
    assert await st.is_locked("l") is False


class BrokenRedis(FakeRedis):
    async def get(self, k):
        raise ConnectionError("down")


@pytest.mark.anyio
async def test_get_json_read_error_is_not_absent():
    from app.services.redis_state import StoreError
    st = RedisState(client=BrokenRedis())
    with pytest.raises(StoreError):
        await st.get_json("k")
