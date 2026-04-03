"""Tests for agents.strategy_rules module."""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from coin_trader.agents.strategy_rules import StrategyRulesAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.message import TickerMessage


@pytest.fixture
def rules_agent(app_config: AppConfig, mock_bus: AsyncMock) -> StrategyRulesAgent:
    agent = StrategyRulesAgent(app_config)
    agent.bus = mock_bus
    return agent


class TestEvaluateEntry:
    @pytest.mark.asyncio
    async def test_no_signal_when_insufficient_data(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """No signal emitted when there is no price history."""
        await rules_agent._evaluate_entry("KRW-BTC")
        rules_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_signal_when_rise_below_threshold(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """No signal when price rise is below 3%."""
        now = time.monotonic()
        history = rules_agent._price_history["KRW-BTC"]
        # +2% rise (below 3% threshold)
        history.append((now - 200, Decimal("100000000")))
        history.append((now, Decimal("102000000")))

        await rules_agent._evaluate_entry("KRW-BTC")
        rules_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_signal_when_rise_meets_threshold(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """BUY signal emitted when price rises >= 3% in the lookback window."""
        now = time.monotonic()
        history = rules_agent._price_history["KRW-BTC"]
        # +3.5% rise
        history.append((now - 200, Decimal("100000000")))
        history.append((now, Decimal("103500000")))

        await rules_agent._evaluate_entry("KRW-BTC")
        rules_agent.bus.publish.assert_awaited_once()

        call_args = rules_agent.bus.publish.call_args
        assert call_args[0][0] == "signal:rules"
        signal = call_args[0][1]
        assert signal.direction.value == "BUY"
        assert signal.strategy == "rules"
        assert signal.confidence == 0.95

    @pytest.mark.asyncio
    async def test_exact_threshold_triggers_signal(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """Signal emitted at exactly +3%."""
        now = time.monotonic()
        history = rules_agent._price_history["KRW-BTC"]
        history.append((now - 200, Decimal("100000000")))
        history.append((now, Decimal("103000000")))

        await rules_agent._evaluate_entry("KRW-BTC")
        rules_agent.bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stale_prices_pruned(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """Prices older than the lookback window are pruned."""
        now = time.monotonic()
        history = rules_agent._price_history["KRW-BTC"]
        # Old price outside lookback window (>300s ago)
        history.append((now - 400, Decimal("50000000")))
        # Recent prices within window — modest rise
        history.append((now - 100, Decimal("100000000")))
        history.append((now, Decimal("101000000")))  # +1% from recent

        await rules_agent._evaluate_entry("KRW-BTC")
        # The old 50M price should be pruned; remaining rise is only 1%
        rules_agent.bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_signal_on_price_drop(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        """No signal when price drops."""
        now = time.monotonic()
        history = rules_agent._price_history["KRW-BTC"]
        history.append((now - 200, Decimal("100000000")))
        history.append((now, Decimal("95000000")))  # -5%

        await rules_agent._evaluate_entry("KRW-BTC")
        rules_agent.bus.publish.assert_not_awaited()


class TestOnTicker:
    @pytest.mark.asyncio
    async def test_ticker_appended_to_history(
        self, rules_agent: StrategyRulesAgent
    ) -> None:
        msg = TickerMessage(
            source_agent="test",
            market="KRW-BTC",
            trade_price=Decimal("95000000"),
            signed_change_rate=0.01,
            acc_trade_volume_24h=Decimal("1000"),
            highest_52_week_price=Decimal("100000000"),
            lowest_52_week_price=Decimal("50000000"),
        )
        await rules_agent._on_ticker("market:ticker:KRW-BTC", msg)
        assert len(rules_agent._price_history["KRW-BTC"]) == 1
        assert rules_agent._price_history["KRW-BTC"][0][1] == Decimal("95000000")
