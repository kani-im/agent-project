"""Tests for agents.executor module — dry-run behaviour."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from coin_trader.agents.executor import ExecutorAgent
from coin_trader.core.config import AppConfig, TradingMode
from coin_trader.core.message import (
    OrderRequestMessage,
    OrderSide,
    OrderStatus,
    OrderType,
)


@pytest.fixture
def dry_run_executor(app_config: AppConfig, mock_bus: AsyncMock) -> ExecutorAgent:
    app_config.trading.mode = TradingMode.DRY_RUN
    agent = ExecutorAgent(app_config)
    agent.bus = mock_bus
    return agent


@pytest.fixture
def live_executor(app_config: AppConfig, mock_bus: AsyncMock) -> ExecutorAgent:
    app_config.trading.mode = TradingMode.LIVE
    agent = ExecutorAgent(app_config)
    agent.bus = mock_bus
    return agent


class TestDryRunMode:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_rest(self, dry_run_executor: ExecutorAgent) -> None:
        dry_run_executor._rest = AsyncMock()

        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        await dry_run_executor._execute_order(order)

        # Should NOT have called the REST client
        dry_run_executor._rest.create_order.assert_not_awaited()

        # Should have published a synthetic fill
        dry_run_executor.bus.publish.assert_awaited_once()
        call_args = dry_run_executor.bus.publish.call_args
        assert call_args[0][0] == "order:filled"
        result = call_args[0][1]
        assert result.order_uuid == "dry-run"
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_dry_run_flag_set(self, dry_run_executor: ExecutorAgent) -> None:
        assert dry_run_executor._dry_run is True

    @pytest.mark.asyncio
    async def test_live_flag_not_dry_run(self, live_executor: ExecutorAgent) -> None:
        assert live_executor._dry_run is False
