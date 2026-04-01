"""Tests for agents.portfolio_manager module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from coin_trader.agents.portfolio_manager import PortfolioManagerAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.message import Direction, SignalMessage


@pytest.fixture
def pm_agent(app_config: AppConfig, mock_bus: AsyncMock) -> PortfolioManagerAgent:
    agent = PortfolioManagerAgent(app_config)
    agent.bus = mock_bus
    agent._rest = AsyncMock()
    agent._krw_balance = Decimal("500000")
    return agent


class TestMakeDecision:
    @pytest.mark.asyncio
    async def test_hold_does_not_publish(self, pm_agent: PortfolioManagerAgent) -> None:
        # No signals -> HOLD
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_buy_signal_publishes_order(self, pm_agent: PortfolioManagerAgent) -> None:
        # Feed strong buy signals
        for strategy in ["ta", "ml", "sentiment"]:
            pm_agent._combiner.update(
                SignalMessage(
                    source_agent="test",
                    market="KRW-BTC",
                    direction=Direction.BUY,
                    confidence=0.9,
                    strategy=strategy,
                )
            )
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_awaited_once()
        call_args = pm_agent.bus.publish.call_args
        assert call_args[0][0] == "order:request"

    @pytest.mark.asyncio
    async def test_sell_signal_with_position(self, pm_agent: PortfolioManagerAgent) -> None:
        pm_agent._positions["KRW-BTC"] = Decimal("0.01")
        for strategy in ["ta", "ml", "sentiment"]:
            pm_agent._combiner.update(
                SignalMessage(
                    source_agent="test",
                    market="KRW-BTC",
                    direction=Direction.SELL,
                    confidence=0.9,
                    strategy=strategy,
                )
            )
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_awaited_once()
        call_args = pm_agent.bus.publish.call_args
        assert call_args[0][0] == "order:request"

    @pytest.mark.asyncio
    async def test_sell_signal_without_position_no_order(self, pm_agent: PortfolioManagerAgent) -> None:
        # No position -> sell signal should not generate order
        for strategy in ["ta", "ml", "sentiment"]:
            pm_agent._combiner.update(
                SignalMessage(
                    source_agent="test",
                    market="KRW-BTC",
                    direction=Direction.SELL,
                    confidence=0.9,
                    strategy=strategy,
                )
            )
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_orders(self, pm_agent: PortfolioManagerAgent) -> None:
        import time

        for strategy in ["ta", "ml", "sentiment"]:
            pm_agent._combiner.update(
                SignalMessage(
                    source_agent="test",
                    market="KRW-BTC",
                    direction=Direction.BUY,
                    confidence=0.9,
                    strategy=strategy,
                )
            )
        # First decision should publish
        await pm_agent._make_decision("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1

        # Re-add signals (combiner still has them)
        # Second decision within cooldown should not publish
        await pm_agent._make_decision("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_low_balance_no_buy(self, pm_agent: PortfolioManagerAgent) -> None:
        pm_agent._krw_balance = Decimal("3000")  # Below 5000 minimum
        for strategy in ["ta", "ml", "sentiment"]:
            pm_agent._combiner.update(
                SignalMessage(
                    source_agent="test",
                    market="KRW-BTC",
                    direction=Direction.BUY,
                    confidence=0.9,
                    strategy=strategy,
                )
            )
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()


class TestOnSignal:
    @pytest.mark.asyncio
    async def test_updates_combiner(self, pm_agent: PortfolioManagerAgent) -> None:
        signal = SignalMessage(
            source_agent="ta-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.8,
            strategy="ta",
        )
        await pm_agent._on_signal("signal:ta", signal)
        # Verify combiner has the signal
        direction, _ = pm_agent._combiner.evaluate("KRW-BTC")
        assert direction == Direction.BUY
