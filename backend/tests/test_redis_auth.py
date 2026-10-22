"""Redis authentication — verify REDIS_PASSWORD is passed to the client."""

from unittest.mock import AsyncMock, MagicMock, patch


async def test_redis_state_passes_password_when_set():
    from app.services import redis_state as rs

    fake_client = MagicMock()
    fake_client.ping = AsyncMock(return_value=True)

    with patch.object(rs, "get_settings") as gs, \
            patch("app.services.redis_state.aioredis.from_url", return_value=fake_client) as from_url:
        gs.return_value = MagicMock(
            redis_url="redis://redis-service:6379/0",
            redis_password="s3cr3t",
            redis_key_prefix="crophealth:",
            sliding_window_hours=48,
        )
        await rs.RedisState.create()

    assert from_url.call_args.kwargs.get("password") == "s3cr3t"


async def test_redis_state_password_none_when_empty():
    from app.services import redis_state as rs

    fake_client = MagicMock()
    fake_client.ping = AsyncMock(return_value=True)

    with patch.object(rs, "get_settings") as gs, \
            patch("app.services.redis_state.aioredis.from_url", return_value=fake_client) as from_url:
        gs.return_value = MagicMock(
            redis_url="redis://localhost:6379/0",
            redis_password="",
            redis_key_prefix="crophealth:",
            sliding_window_hours=48,
        )
        await rs.RedisState.create()

    assert from_url.call_args.kwargs.get("password") is None
