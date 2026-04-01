"""Redis Streams based message bus for inter-agent communication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from coin_trader.core.logging import get_logger
from coin_trader.core.message import BaseMessage

log = get_logger(__name__)

# Max messages per stream to prevent unbounded memory growth
STREAM_MAXLEN = 10_000


class RedisBus:
    """Async Redis Streams wrapper for agent communication."""

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=False)
        await self._redis.ping()
        log.info("redis_connected", url=self._url)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            log.info("redis_disconnected")

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("RedisBus not connected. Call connect() first.")
        return self._redis

    async def publish(self, stream: str, message: BaseMessage) -> str:
        """Publish a message to a Redis Stream. Returns the message ID."""
        msg_id = await self.redis.xadd(
            stream,
            message.to_redis(),
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        return msg_id.decode() if isinstance(msg_id, bytes) else msg_id

    async def ensure_group(self, stream: str, group: str) -> None:
        """Create a consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def subscribe(
        self,
        streams: list[str],
        group: str,
        consumer: str,
        handler: Callable[[str, BaseMessage], Awaitable[None]],
        batch_size: int = 10,
        block_ms: int = 1000,
    ) -> None:
        """Subscribe to streams via consumer group and process messages.

        This method runs indefinitely until cancelled.
        """
        for stream in streams:
            await self.ensure_group(stream, group)

        stream_ids = {stream: ">" for stream in streams}

        while True:
            results: list[Any] = await self.redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams=stream_ids,
                count=batch_size,
                block=block_ms,
            )

            if not results:
                continue

            for stream_bytes, messages in results:
                stream_name = (
                    stream_bytes.decode()
                    if isinstance(stream_bytes, bytes)
                    else stream_bytes
                )
                for msg_id, msg_data in messages:
                    try:
                        message = BaseMessage.from_redis(msg_data)
                        await handler(stream_name, message)
                        await self.redis.xack(stream_name, group, msg_id)
                    except Exception:
                        log.exception(
                            "message_processing_error",
                            stream=stream_name,
                            msg_id=msg_id,
                        )

    async def get_latest(self, stream: str, count: int = 1) -> list[BaseMessage]:
        """Get the latest N messages from a stream."""
        results = await self.redis.xrevrange(stream, count=count)
        messages = []
        for _msg_id, msg_data in results:
            try:
                messages.append(BaseMessage.from_redis(msg_data))
            except Exception:
                log.exception("deserialize_error", stream=stream)
        return messages
