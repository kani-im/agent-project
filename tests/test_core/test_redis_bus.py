"""Tests for core.redis_bus module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coin_trader.core.message import HeartbeatMessage
from coin_trader.core.redis_bus import STREAM_MAXLEN, RedisBus


class TestRedisBus:
    def test_not_connected_raises(self) -> None:
        bus = RedisBus("redis://localhost:6379/0")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = bus.redis

    @pytest.mark.asyncio
    async def test_connect_and_close(self) -> None:
        bus = RedisBus("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("coin_trader.core.redis_bus.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            await bus.connect()
            assert bus._redis is mock_redis
            mock_redis.ping.assert_awaited_once()

            await bus.close()
            mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish(self) -> None:
        bus = RedisBus("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1-0")
        bus._redis = mock_redis

        msg = HeartbeatMessage(source_agent="test", agent_type="test")
        result = await bus.publish("stream:test", msg)

        assert result == "1-0"
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "stream:test"
        assert call_args[1]["maxlen"] == STREAM_MAXLEN

    @pytest.mark.asyncio
    async def test_ensure_group_creates(self) -> None:
        bus = RedisBus("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        await bus.ensure_group("stream:test", "my-group")
        mock_redis.xgroup_create.assert_awaited_once_with(
            "stream:test", "my-group", id="0", mkstream=True
        )

    @pytest.mark.asyncio
    async def test_ensure_group_ignores_busygroup(self) -> None:
        import redis.asyncio as aioredis

        bus = RedisBus("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        bus._redis = mock_redis

        # Should not raise
        await bus.ensure_group("stream:test", "my-group")

    @pytest.mark.asyncio
    async def test_get_latest(self) -> None:
        bus = RedisBus("redis://localhost:6379/0")
        msg = HeartbeatMessage(source_agent="test", agent_type="monitor")
        redis_data = {k.encode(): v.encode() for k, v in msg.to_redis().items()}

        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(return_value=[(b"1-0", redis_data)])
        bus._redis = mock_redis

        results = await bus.get_latest("stream:test", count=1)
        assert len(results) == 1
        assert isinstance(results[0], HeartbeatMessage)
        assert results[0].agent_type == "monitor"
