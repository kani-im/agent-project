"""Tests for core.base_agent module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig


class ConcreteAgent(BaseAgent):
    """Minimal agent for testing the base class."""

    agent_type = "test_agent"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self.setup_called = False
        self.run_called = False
        self.teardown_called = False

    async def setup(self) -> None:
        self.setup_called = True

    async def run(self) -> None:
        self.run_called = True
        # Simulate short-lived run
        while self._running:
            await asyncio.sleep(0.01)

    async def teardown(self) -> None:
        self.teardown_called = True


class TestBaseAgent:
    def test_agent_id_contains_type(self, app_config: AppConfig) -> None:
        agent = ConcreteAgent(app_config)
        assert "test_agent" in agent.agent_id

    def test_initial_state(self, app_config: AppConfig) -> None:
        agent = ConcreteAgent(app_config)
        assert not agent._running
        assert agent._tasks == []

    @pytest.mark.asyncio
    async def test_shutdown_sets_running_false(self, app_config: AppConfig) -> None:
        agent = ConcreteAgent(app_config)
        agent._running = True
        await agent.shutdown()
        assert not agent._running

    @pytest.mark.asyncio
    async def test_start_lifecycle(self, app_config: AppConfig) -> None:
        agent = ConcreteAgent(app_config)
        agent.bus = AsyncMock()
        agent.bus.connect = AsyncMock()
        agent.bus.close = AsyncMock()
        agent.bus.publish = AsyncMock(return_value=b"1-0")

        # Schedule shutdown after a short delay
        async def auto_shutdown():
            await asyncio.sleep(0.05)
            agent._running = False

        with patch("coin_trader.core.base_agent.asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.add_signal_handler = lambda *a, **kw: None

            task = asyncio.create_task(agent.start())
            shutdown_task = asyncio.create_task(auto_shutdown())

            await asyncio.wait_for(task, timeout=2.0)

        assert agent.setup_called
        assert agent.run_called
        assert agent.teardown_called
        agent.bus.connect.assert_awaited_once()
        agent.bus.close.assert_awaited_once()
