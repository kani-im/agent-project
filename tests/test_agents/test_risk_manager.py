"""Tests for agents.risk_manager module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from coin_trader.agents.risk_manager import RiskManagerAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.message import (
    OrderRequestMessage,
    OrderResultMessage,
    OrderSide,
    OrderStatus,
    OrderType,
    TickerMessage,
)


@pytest.fixture
def risk_agent(app_config: AppConfig, mock_bus: AsyncMock) -> RiskManagerAgent:
    agent = RiskManagerAgent(app_config)
    agent.bus = mock_bus
    agent._total_balance = Decimal("1000000")
    return agent


class TestValidateOrder:
    def test_valid_buy_order(self, risk_agent: RiskManagerAgent) -> None:
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        assert risk_agent._validate_order(order) is None

    def test_reject_exceeds_single_order_limit(self, risk_agent: RiskManagerAgent) -> None:
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("60000"),  # Exceeds 50000 limit
        )
        reason = risk_agent._validate_order(order)
        assert reason is not None
        assert "exceeds max" in reason

    def test_reject_daily_loss_exceeded(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._daily_pnl = Decimal("-150000")
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        reason = risk_agent._validate_order(order)
        assert reason is not None
        assert "Daily loss limit" in reason

    def test_reject_halted(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._halted = True
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        reason = risk_agent._validate_order(order)
        assert reason is not None
        assert "halted" in reason

    def test_reject_max_open_positions(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._open_positions = 999  # Matches new default (no practical limit)
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        reason = risk_agent._validate_order(order)
        assert reason is not None
        assert "Max open positions" in reason

    def test_reject_position_ratio_exceeded(self, risk_agent: RiskManagerAgent) -> None:
        # Already holding 250K of a 1M portfolio (25%)
        risk_agent._positions["KRW-BTC"] = Decimal("250000")
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("60000"),  # Would push to 31% > 30%
        )
        # Note: amount_krw of 60K exceeds 50K limit first
        reason = risk_agent._validate_order(order)
        assert reason is not None

    def test_sell_order_bypasses_position_checks(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._open_positions = 5  # At max
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.ASK,
            order_type=OrderType.MARKET,
            volume=Decimal("0.001"),
        )
        # Sell should be allowed even at max positions
        reason = risk_agent._validate_order(order)
        assert reason is None


class TestKillSwitch:
    def test_reject_when_trading_disabled(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent.config.trading.enabled = False
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        reason = risk_agent._validate_order(order)
        assert reason is not None
        assert "kill switch" in reason.lower()

    def test_allow_when_trading_enabled(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent.config.trading.enabled = True
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("10000"),
        )
        assert risk_agent._validate_order(order) is None


class TestEstimateOrderAmount:
    def test_from_amount_krw(self, risk_agent: RiskManagerAgent) -> None:
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("50000"),
        )
        assert risk_agent._estimate_order_amount(order) == Decimal("50000")

    def test_from_price_and_volume(self, risk_agent: RiskManagerAgent) -> None:
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.LIMIT,
            price=Decimal("90000000"),
            volume=Decimal("0.001"),
        )
        assert risk_agent._estimate_order_amount(order) == Decimal("90000")

    def test_from_current_price(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._prices["KRW-BTC"] = Decimal("90000000")
        order = OrderRequestMessage(
            source_agent="test",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            volume=Decimal("0.001"),
        )
        assert risk_agent._estimate_order_amount(order) == Decimal("90000")


class TestOnOrderResult:
    @pytest.mark.asyncio
    async def test_buy_increases_position(self, risk_agent: RiskManagerAgent) -> None:
        msg = OrderResultMessage(
            source_agent="exec",
            order_uuid="123",
            market="KRW-BTC",
            side=OrderSide.BID,
            status=OrderStatus.FILLED,
            executed_volume=Decimal("0.001"),
            executed_price=Decimal("90000000"),
            fee=Decimal("45"),
        )
        await risk_agent._on_order_result("order:filled", msg)
        assert risk_agent._positions["KRW-BTC"] == Decimal("90000")
        assert risk_agent._open_positions == 1

    @pytest.mark.asyncio
    async def test_sell_decreases_position(self, risk_agent: RiskManagerAgent) -> None:
        risk_agent._positions["KRW-BTC"] = Decimal("90000")
        msg = OrderResultMessage(
            source_agent="exec",
            order_uuid="123",
            market="KRW-BTC",
            side=OrderSide.ASK,
            status=OrderStatus.FILLED,
            executed_volume=Decimal("0.001"),
            executed_price=Decimal("90000000"),
            fee=Decimal("45"),
        )
        await risk_agent._on_order_result("order:filled", msg)
        assert risk_agent._positions["KRW-BTC"] == Decimal("0")


class TestDailyReset:
    def test_resets_after_24h(self, risk_agent: RiskManagerAgent) -> None:
        import time

        risk_agent._daily_pnl = Decimal("-50000")
        risk_agent._halted = True
        risk_agent._daily_reset_time = time.time() - 90000  # >24h ago
        risk_agent._check_daily_reset()
        assert risk_agent._daily_pnl == Decimal("0")
        assert not risk_agent._halted

    def test_no_reset_within_24h(self, risk_agent: RiskManagerAgent) -> None:
        import time

        risk_agent._daily_pnl = Decimal("-50000")
        risk_agent._daily_reset_time = time.time() - 1000  # <24h
        risk_agent._check_daily_reset()
        assert risk_agent._daily_pnl == Decimal("-50000")
