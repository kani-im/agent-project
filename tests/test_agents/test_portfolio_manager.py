"""Tests for agents.portfolio_manager module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from coin_trader.agents.portfolio_manager import PortfolioManagerAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.message import Direction, SignalMessage, TickerMessage


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


class TestRuleBasedBuy:
    @pytest.mark.asyncio
    async def test_rule_signal_triggers_buy(self, pm_agent: PortfolioManagerAgent) -> None:
        """A rule-based BUY signal produces an order:request."""
        signal = SignalMessage(
            source_agent="rules-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.95,
            strategy="rules",
        )
        await pm_agent._on_signal("signal:rules", signal)
        await pm_agent._make_decision("KRW-BTC")
        pm_agent.bus.publish.assert_awaited_once()
        call_args = pm_agent.bus.publish.call_args
        assert call_args[0][0] == "order:request"
        order = call_args[0][1]
        assert order.side.value == "bid"
        # Buy amount should be capped at max_entry_krw (50000)
        assert order.amount_krw <= Decimal("50000")

    @pytest.mark.asyncio
    async def test_rule_buy_respects_max_entry(self, pm_agent: PortfolioManagerAgent) -> None:
        """Rule-based buy amount is capped at max_entry_krw."""
        pm_agent._krw_balance = Decimal("1000000")
        signal = SignalMessage(
            source_agent="rules-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.95,
            strategy="rules",
        )
        await pm_agent._on_signal("signal:rules", signal)
        await pm_agent._make_decision("KRW-BTC")
        order = pm_agent.bus.publish.call_args[0][1]
        assert order.amount_krw == Decimal("50000")

    @pytest.mark.asyncio
    async def test_rule_buy_cooldown(self, pm_agent: PortfolioManagerAgent) -> None:
        """Rule-based buy respects cooldown."""
        signal = SignalMessage(
            source_agent="rules-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.95,
            strategy="rules",
        )
        # First buy
        await pm_agent._on_signal("signal:rules", signal)
        await pm_agent._make_decision("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1

        # Second buy within cooldown
        await pm_agent._on_signal("signal:rules", signal)
        await pm_agent._make_decision("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1  # Still 1


class TestExitRules:
    @pytest.mark.asyncio
    async def test_take_profit_triggers_sell(self, pm_agent: PortfolioManagerAgent) -> None:
        """Position is sold when profit reaches +5%."""
        pm_agent._positions["KRW-BTC"] = Decimal("0.001")
        pm_agent._avg_buy_prices["KRW-BTC"] = Decimal("100000000")
        pm_agent._current_prices["KRW-BTC"] = Decimal("105100000")  # +5.1%

        await pm_agent._check_exit_rules("KRW-BTC")
        pm_agent.bus.publish.assert_awaited_once()
        call_args = pm_agent.bus.publish.call_args
        assert call_args[0][0] == "order:request"
        order = call_args[0][1]
        assert order.side.value == "ask"
        assert order.volume == Decimal("0.001")

    @pytest.mark.asyncio
    async def test_stop_loss_triggers_sell(self, pm_agent: PortfolioManagerAgent) -> None:
        """Position is sold when loss reaches -2%."""
        pm_agent._positions["KRW-BTC"] = Decimal("0.001")
        pm_agent._avg_buy_prices["KRW-BTC"] = Decimal("100000000")
        pm_agent._current_prices["KRW-BTC"] = Decimal("97900000")  # -2.1%

        await pm_agent._check_exit_rules("KRW-BTC")
        pm_agent.bus.publish.assert_awaited_once()
        order = pm_agent.bus.publish.call_args[0][1]
        assert order.side.value == "ask"

    @pytest.mark.asyncio
    async def test_no_exit_within_thresholds(self, pm_agent: PortfolioManagerAgent) -> None:
        """No sell when P&L is between -2% and +5%."""
        pm_agent._positions["KRW-BTC"] = Decimal("0.001")
        pm_agent._avg_buy_prices["KRW-BTC"] = Decimal("100000000")
        pm_agent._current_prices["KRW-BTC"] = Decimal("102000000")  # +2%

        await pm_agent._check_exit_rules("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_exit_without_position(self, pm_agent: PortfolioManagerAgent) -> None:
        """No exit check when there is no position."""
        pm_agent._current_prices["KRW-BTC"] = Decimal("50000000")
        await pm_agent._check_exit_rules("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_exit_without_price(self, pm_agent: PortfolioManagerAgent) -> None:
        """No exit check when current price is unknown."""
        pm_agent._positions["KRW-BTC"] = Decimal("0.001")
        pm_agent._avg_buy_prices["KRW-BTC"] = Decimal("100000000")
        # No current price set
        await pm_agent._check_exit_rules("KRW-BTC")
        pm_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exit_respects_cooldown(self, pm_agent: PortfolioManagerAgent) -> None:
        """Exit rules respect order cooldown."""
        import time

        pm_agent._positions["KRW-BTC"] = Decimal("0.001")
        pm_agent._avg_buy_prices["KRW-BTC"] = Decimal("100000000")
        pm_agent._current_prices["KRW-BTC"] = Decimal("106000000")  # +6%

        # First exit triggers
        await pm_agent._check_exit_rules("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1

        # Second call within cooldown doesn't trigger
        await pm_agent._check_exit_rules("KRW-BTC")
        assert pm_agent.bus.publish.await_count == 1


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

    @pytest.mark.asyncio
    async def test_rule_signal_stored_as_pending(self, pm_agent: PortfolioManagerAgent) -> None:
        """Rule-based signals are stored separately, not in the combiner."""
        signal = SignalMessage(
            source_agent="rules-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.95,
            strategy="rules",
        )
        await pm_agent._on_signal("signal:rules", signal)
        assert "KRW-BTC" in pm_agent._pending_rule_buys
        # Combiner should not have this signal
        direction, _ = pm_agent._combiner.evaluate("KRW-BTC")
        assert direction == Direction.HOLD


class TestOnTicker:
    @pytest.mark.asyncio
    async def test_ticker_updates_current_price(self, pm_agent: PortfolioManagerAgent) -> None:
        msg = TickerMessage(
            source_agent="test",
            market="KRW-BTC",
            trade_price=Decimal("95000000"),
            signed_change_rate=0.01,
            acc_trade_volume_24h=Decimal("1000"),
            highest_52_week_price=Decimal("100000000"),
            lowest_52_week_price=Decimal("50000000"),
        )
        await pm_agent._on_ticker("market:ticker:KRW-BTC", msg)
        assert pm_agent._current_prices["KRW-BTC"] == Decimal("95000000")
