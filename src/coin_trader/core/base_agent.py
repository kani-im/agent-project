"""Base agent class providing lifecycle management and Redis communication."""

from __future__ import annotations

import asyncio
import signal
from abc import ABC, abstractmethod

from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import HeartbeatMessage
from coin_trader.core.redis_bus import RedisBus

log = get_logger(__name__)

HEARTBEAT_INTERVAL = 5.0


class BaseAgent(ABC):
    """Base class for all trading agents."""

    agent_type: str = "base"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.bus = RedisBus(config.redis.url)
        self._running = False
        self._tasks: list[asyncio.Task] = []

    @property
    def agent_id(self) -> str:
        return f"{self.agent_type}-{id(self):x}"

    async def start(self) -> None:
        """Start the agent: connect -> setup -> run loop -> teardown."""
        log.info("agent_starting", agent=self.agent_id, type=self.agent_type)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        await self.bus.connect()
        await self.setup()
        self._running = True

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._tasks.append(heartbeat_task)

        try:
            await self.run()
        except asyncio.CancelledError:
            log.info("agent_cancelled", agent=self.agent_id)
        finally:
            self._running = False
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await self.teardown()
            await self.bus.close()
            log.info("agent_stopped", agent=self.agent_id)

    async def _heartbeat_loop(self) -> None:
        """Publish periodic heartbeat messages."""
        while self._running:
            try:
                msg = HeartbeatMessage(
                    source_agent=self.agent_id,
                    agent_type=self.agent_type,
                )
                await self.bus.publish("system:heartbeat", msg)
            except Exception:
                log.exception("heartbeat_error", agent=self.agent_id)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    @abstractmethod
    async def setup(self) -> None:
        """Initialize agent-specific resources."""

    @abstractmethod
    async def run(self) -> None:
        """Main agent loop. Should run until self._running is False."""

    async def teardown(self) -> None:
        """Cleanup agent-specific resources. Override if needed."""

    async def shutdown(self) -> None:
        """Trigger graceful shutdown."""
        log.info("agent_shutting_down", agent=self.agent_id)
        self._running = False
