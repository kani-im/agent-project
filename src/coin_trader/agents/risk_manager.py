"""Risk Manager Agent - Validates orders against risk limits.

Respects the global kill switch (``TRADING_ENABLED=false``) which
causes *all* incoming orders to be rejected immediately.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    AlertMessage,
    BaseMessage,
    OrderRequestMessage,
    OrderResultMessage,
    OrderSide,
    OrderStatus,
    TickerMessage,
)
from coin_trader.core.notifier import Event, Notifier

log = get_logger(__name__)


class RiskManagerAgent(BaseAgent):
    agent_type = "risk_manager"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._notifier = Notifier.from_config(config.notification)
        # market -> current position value in KRW
        self._positions: dict[str, Decimal] = {}
        # Total portfolio value (cash + positions)
        self._total_balance: Decimal = Decimal("0")
        # Daily realized P&L
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_reset_time: float = 0.0
        # Current prices
        self._prices: dict[str, Decimal] = {}
        # Number of open positions
        self._open_positions: int = 0
        # Peak balance for drawdown tracking
        self._peak_balance: Decimal = Decimal("0")
        # Trading halted flag
        self._halted: bool = False

    async def setup(self) -> None:
        self._daily_reset_time = time.time()
        log.info(
            "risk_manager_setup",
            max_position_ratio=self.config.risk.max_position_ratio,
            max_daily_loss=self.config.risk.max_daily_loss_krw,
        )

    async def run(self) -> None:
        markets = self.config.strategy.target_markets
        ticker_streams = [f"market:ticker:{m}" for m in markets]

        # Subscribe to order requests
        order_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["order:request"],
                group="risk_manager",
                consumer=self.agent_id,
                handler=self._on_order_request,
            )
        )
        self._tasks.append(order_task)

        # Subscribe to order results (to track P&L)
        result_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["order:filled", "order:failed"],
                group="risk_manager_results",
                consumer=self.agent_id,
                handler=self._on_order_result,
            )
        )
        self._tasks.append(result_task)

        # Subscribe to tickers for price tracking
        ticker_task = asyncio.create_task(
            self.bus.subscribe(
                streams=ticker_streams,
                group="risk_manager_ticker",
                consumer=self.agent_id,
                handler=self._on_ticker,
            )
        )
        self._tasks.append(ticker_task)

        # Daily reset loop
        while self._running:
            self._check_daily_reset()
            await asyncio.sleep(60)

    async def _on_ticker(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, TickerMessage):
            self._prices[message.market] = message.trade_price

    async def _on_order_result(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, OrderResultMessage):
            if message.status == OrderStatus.FILLED:
                if message.side == OrderSide.ASK:
                    # Sold - reduce position
                    current = self._positions.get(message.market, Decimal("0"))
                    sold_value = message.executed_volume * message.executed_price
                    self._positions[message.market] = max(
                        Decimal("0"), current - sold_value
                    )
                elif message.side == OrderSide.BID:
                    # Bought - increase position
                    current = self._positions.get(message.market, Decimal("0"))
                    bought_value = message.executed_volume * message.executed_price
                    self._positions[message.market] = current + bought_value

                self._open_positions = sum(
                    1 for v in self._positions.values() if v > 0
                )

    async def _on_order_request(self, stream: str, message: BaseMessage) -> None:
        if not isinstance(message, OrderRequestMessage):
            return

        rejection_reason = self._validate_order(message)

        if rejection_reason:
            log.warning(
                "order_rejected",
                market=message.market,
                reason=rejection_reason,
            )
            alert = AlertMessage(
                source_agent=self.agent_id,
                level="warning",
                title="Order Rejected",
                detail=f"{message.market} {message.side.value}: {rejection_reason}",
            )
            await self.bus.publish("order:rejected", message)
            await self.bus.publish("alert:risk", alert)
            await self._notifier.notify(
                Event.ORDER_FAILURE,
                f"Order rejected: {message.market} {message.side.value} — {rejection_reason}",
            )
        else:
            log.info("order_approved", market=message.market, side=message.side.value)
            await self.bus.publish("order:approved", message)

    def _validate_order(self, order: OrderRequestMessage) -> str | None:
        """Validate order against risk limits. Returns rejection reason or None."""
        # Kill switch — reject everything when trading is disabled
        if not self.config.trading.enabled:
            return "Trading is disabled (kill switch)"

        risk = self.config.risk

        # Check if trading is halted
        if self._halted:
            return "Trading halted due to risk limits"

        # Check daily loss limit
        if self._daily_pnl < -Decimal(str(risk.max_daily_loss_krw)):
            self._halted = True
            return f"Daily loss limit exceeded: {self._daily_pnl} KRW"

        # Check drawdown limit
        if self._peak_balance > 0:
            current_balance = sum(self._positions.values())
            drawdown = (self._peak_balance - current_balance) / self._peak_balance
            if drawdown > Decimal(str(risk.drawdown_limit)):
                self._halted = True
                return f"Drawdown limit exceeded: {float(drawdown):.2%}"

        # Check single order size
        order_amount = self._estimate_order_amount(order)
        if order_amount and order_amount > Decimal(str(risk.max_single_order_krw)):
            return f"Order amount {order_amount} exceeds max {risk.max_single_order_krw} KRW"

        # Check position ratio (only for buy orders)
        if order.side == OrderSide.BID:
            current_position = self._positions.get(order.market, Decimal("0"))
            new_position = current_position + (order_amount or Decimal("0"))
            if self._total_balance > 0:
                ratio = new_position / self._total_balance
                if ratio > Decimal(str(risk.max_position_ratio)):
                    return f"Position ratio {float(ratio):.1%} exceeds max {risk.max_position_ratio:.0%}"

            # Check max open positions
            if (
                current_position == 0
                and self._open_positions >= risk.max_open_positions
            ):
                return f"Max open positions ({risk.max_open_positions}) reached"

        return None

    def _estimate_order_amount(self, order: OrderRequestMessage) -> Decimal | None:
        """Estimate order amount in KRW."""
        if order.amount_krw:
            return order.amount_krw
        if order.price and order.volume:
            return order.price * order.volume
        price = self._prices.get(order.market)
        if price and order.volume:
            return price * order.volume
        return None

    def _check_daily_reset(self) -> None:
        """Reset daily P&L at midnight."""
        now = time.time()
        # Reset every 24 hours
        if now - self._daily_reset_time > 86400:
            self._daily_pnl = Decimal("0")
            self._daily_reset_time = now
            self._halted = False
            log.info("daily_risk_reset")
