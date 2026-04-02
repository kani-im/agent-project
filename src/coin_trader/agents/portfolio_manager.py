"""Portfolio Manager Agent - Orchestrates signal combination and order decisions."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    BaseMessage,
    Direction,
    OrderRequestMessage,
    OrderResultMessage,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalMessage,
)
from coin_trader.exchange.rest_client import UpbitRestClient
from coin_trader.strategies.combiner import SignalCombiner

log = get_logger(__name__)

# How often to check signals and make decisions
DECISION_INTERVAL = 15.0

# Minimum time between orders for the same market (seconds)
ORDER_COOLDOWN = 120.0


class PortfolioManagerAgent(BaseAgent):
    agent_type = "portfolio_manager"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._combiner = SignalCombiner(
            weights={
                "ta": config.strategy.weights.ta,
                "ml": config.strategy.weights.ml,
                "sentiment": config.strategy.weights.sentiment,
            },
            min_confidence=config.strategy.min_combined_confidence,
        )
        self._rest: UpbitRestClient | None = None
        # market -> last order timestamp
        self._last_order_time: dict[str, float] = {}
        # market -> current position volume
        self._positions: dict[str, Decimal] = {}
        # Available KRW balance
        self._krw_balance: Decimal = Decimal("0")

    async def setup(self) -> None:
        self._rest = UpbitRestClient(
            access_key=self.config.upbit.access_key.get_secret_value(),
            secret_key=self.config.upbit.secret_key.get_secret_value(),
        )
        # Load initial balances
        await self._refresh_balances()
        log.info(
            "portfolio_manager_setup",
            krw_balance=str(self._krw_balance),
            positions=len(self._positions),
        )

    async def run(self) -> None:
        # Subscribe to all signal streams
        signal_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["signal:ta", "signal:ml", "signal:sentiment"],
                group="portfolio_manager",
                consumer=self.agent_id,
                handler=self._on_signal,
            )
        )
        self._tasks.append(signal_task)

        # Subscribe to order results
        result_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["order:filled", "order:failed", "order:rejected"],
                group="portfolio_manager_orders",
                consumer=self.agent_id,
                handler=self._on_order_result,
            )
        )
        self._tasks.append(result_task)

        # Balance refresh loop
        balance_task = asyncio.create_task(self._balance_refresh_loop())
        self._tasks.append(balance_task)

        # Decision loop
        while self._running:
            for market in self.config.strategy.target_markets:
                await self._make_decision(market)
            await asyncio.sleep(DECISION_INTERVAL)

    async def teardown(self) -> None:
        if self._rest:
            await self._rest.close()

    async def _on_signal(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, SignalMessage):
            self._combiner.update(message)

    async def _on_order_result(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, OrderResultMessage):
            if message.status == OrderStatus.FILLED:
                log.info(
                    "order_filled_notification",
                    market=message.market,
                    side=message.side.value,
                    volume=str(message.executed_volume),
                    price=str(message.executed_price),
                )
                # Refresh balances after fill
                await self._refresh_balances()

    async def _make_decision(self, market: str) -> None:
        """Evaluate combined signals and decide whether to place an order."""
        import time

        direction, confidence = self._combiner.evaluate(market)

        if direction == Direction.HOLD:
            return

        # Check cooldown
        now = time.monotonic()
        if market in self._last_order_time and now - self._last_order_time[market] < ORDER_COOLDOWN:
            return

        # Determine order parameters
        position = self._positions.get(market, Decimal("0"))

        if direction == Direction.BUY and self._krw_balance > Decimal("5000"):
            # Calculate buy amount (use a fraction of available KRW)
            max_order = Decimal(str(self.config.risk.max_single_order_krw))
            buy_amount = min(self._krw_balance * Decimal("0.2"), max_order)
            if buy_amount < Decimal("5000"):
                return  # Upbit minimum order is 5000 KRW

            order = OrderRequestMessage(
                source_agent=self.agent_id,
                market=market,
                side=OrderSide.BID,
                order_type=OrderType.MARKET,
                amount_krw=buy_amount,
            )
            await self.bus.publish("order:request", order)
            self._last_order_time[market] = now
            log.info(
                "buy_order_requested",
                market=market,
                amount_krw=str(buy_amount),
                confidence=round(confidence, 3),
            )

        elif direction == Direction.SELL and position > Decimal("0"):
            # Sell entire position
            order = OrderRequestMessage(
                source_agent=self.agent_id,
                market=market,
                side=OrderSide.ASK,
                order_type=OrderType.MARKET,
                volume=position,
            )
            await self.bus.publish("order:request", order)
            self._last_order_time[market] = now
            log.info(
                "sell_order_requested",
                market=market,
                volume=str(position),
                confidence=round(confidence, 3),
            )

    async def _refresh_balances(self) -> None:
        """Fetch current balances from Upbit."""
        try:
            accounts = await self._rest.get_accounts()
            self._positions.clear()
            for acc in accounts:
                if acc.currency == "KRW":
                    self._krw_balance = acc.balance
                else:
                    market = f"KRW-{acc.currency}"
                    if acc.balance > 0:
                        self._positions[market] = acc.balance
            log.debug(
                "balances_refreshed",
                krw=str(self._krw_balance),
                positions=len(self._positions),
            )
        except Exception:
            log.exception("balance_refresh_error")

    async def _balance_refresh_loop(self) -> None:
        """Periodically refresh balances."""
        while self._running:
            await asyncio.sleep(30)
            await self._refresh_balances()
