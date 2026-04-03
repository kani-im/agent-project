"""Portfolio Manager Agent - Orchestrates signal combination and order decisions.

Extended with explicit rule-based trading logic:
- Treats signals from the "rules" strategy as direct entry triggers.
- Tracks average buy price per position (from Upbit account data).
- Continuously evaluates take-profit (+5%) and stop-loss (-2%) exit rules
  independently of the signal combiner.
"""

from __future__ import annotations

import asyncio
import time
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
    TickerMessage,
)
from coin_trader.core.notifier import Event, Notifier
from coin_trader.exchange.rest_client import UpbitRestClient
from coin_trader.strategies.combiner import SignalCombiner

log = get_logger(__name__)

# How often to check signals and make decisions
DECISION_INTERVAL = 15.0

# Minimum time between orders for the same market (seconds)
ORDER_COOLDOWN = 120.0

# Upbit minimum order amount in KRW
UPBIT_MIN_ORDER_KRW = Decimal("5000")


class PortfolioManagerAgent(BaseAgent):
    agent_type = "portfolio_manager"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._notifier = Notifier.from_config(config.notification)
        self._combiner = SignalCombiner(
            weights={
                "ta": config.strategy.weights.ta,
                "ml": config.strategy.weights.ml,
                "sentiment": config.strategy.weights.sentiment,
            },
            min_confidence=config.strategy.min_combined_confidence,
        )
        self._rest: UpbitRestClient | None = None
        # market -> last order timestamp (monotonic)
        self._last_order_time: dict[str, float] = {}
        # market -> current position volume
        self._positions: dict[str, Decimal] = {}
        # market -> average buy price (KRW per unit, from Upbit account)
        self._avg_buy_prices: dict[str, Decimal] = {}
        # market -> latest trade price (from ticker stream)
        self._current_prices: dict[str, Decimal] = {}
        # Available KRW balance
        self._krw_balance: Decimal = Decimal("0")
        # Pending rule-based buy signals: market -> SignalMessage
        self._pending_rule_buys: dict[str, SignalMessage] = {}
        # Rule strategy config
        self._rules = config.rules

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
        markets = self.config.strategy.target_markets
        ticker_streams = [f"market:ticker:{m}" for m in markets]

        # Subscribe to all signal streams (including rule-based)
        signal_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["signal:ta", "signal:ml", "signal:sentiment", "signal:rules"],
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

        # Subscribe to tickers for current price tracking (used by TP/SL)
        ticker_task = asyncio.create_task(
            self.bus.subscribe(
                streams=ticker_streams,
                group="portfolio_manager_ticker",
                consumer=self.agent_id,
                handler=self._on_ticker,
            )
        )
        self._tasks.append(ticker_task)

        # Balance refresh loop
        balance_task = asyncio.create_task(self._balance_refresh_loop())
        self._tasks.append(balance_task)

        # Decision loop
        while self._running:
            for market in markets:
                await self._check_exit_rules(market)
                await self._make_decision(market)
            await asyncio.sleep(DECISION_INTERVAL)

    async def teardown(self) -> None:
        if self._rest:
            await self._rest.close()

    async def _on_ticker(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, TickerMessage):
            self._current_prices[message.market] = message.trade_price

    async def _on_signal(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, SignalMessage):
            if message.strategy == "rules":
                # Rule-based signals are handled as direct entry triggers
                if message.direction == Direction.BUY:
                    self._pending_rule_buys[message.market] = message
            else:
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
                # Refresh balances after fill to get updated avg_buy_price
                await self._refresh_balances()

    async def _check_exit_rules(self, market: str) -> None:
        """Evaluate take-profit and stop-loss conditions for held positions.

        These checks run independently of the signal combiner.
        If triggered, a SELL order is placed immediately (subject to cooldown).
        """
        position = self._positions.get(market, Decimal("0"))
        if position <= 0:
            return

        avg_price = self._avg_buy_prices.get(market)
        current_price = self._current_prices.get(market)
        if not avg_price or avg_price <= 0 or not current_price:
            return

        pnl_pct = (current_price - avg_price) / avg_price

        reason: str | None = None
        if pnl_pct >= Decimal(str(self._rules.take_profit_pct)):
            reason = "take_profit"
        elif pnl_pct <= -Decimal(str(self._rules.stop_loss_pct)):
            reason = "stop_loss"

        if reason is None:
            return

        # Check cooldown (exit rules share the same cooldown as entry)
        now = time.monotonic()
        if market in self._last_order_time and now - self._last_order_time[market] < ORDER_COOLDOWN:
            return

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
            f"{reason}_triggered",
            market=market,
            volume=str(position),
            avg_buy_price=str(avg_price),
            current_price=str(current_price),
            pnl_pct=f"{float(pnl_pct):.4f}",
        )
        event = Event.TAKE_PROFIT if reason == "take_profit" else Event.STOP_LOSS
        await self._notifier.notify(
            event,
            f"{market} {reason}: pnl={float(pnl_pct):.2%}, avg={avg_price}, cur={current_price}",
        )

    async def _make_decision(self, market: str) -> None:
        """Evaluate signals and decide whether to place a buy order.

        Sell decisions are handled by _check_exit_rules() for rule-based
        trading.  The legacy combiner sell path is kept for non-rules signals.
        """
        now = time.monotonic()

        # --- Rule-based buy ---
        rule_signal = self._pending_rule_buys.pop(market, None)
        if rule_signal is not None:
            await self._try_buy(market, confidence=rule_signal.confidence, source="rules")
            return

        # --- Legacy combiner path ---
        direction, confidence = self._combiner.evaluate(market)

        if direction == Direction.HOLD:
            return

        # Check cooldown
        if market in self._last_order_time and now - self._last_order_time[market] < ORDER_COOLDOWN:
            return

        position = self._positions.get(market, Decimal("0"))

        if direction == Direction.BUY and self._krw_balance > UPBIT_MIN_ORDER_KRW:
            await self._try_buy(market, confidence=confidence, source="combiner")

        elif direction == Direction.SELL and position > Decimal("0"):
            order = OrderRequestMessage(
                source_agent=self.agent_id,
                market=market,
                side=OrderSide.ASK,
                order_type=OrderType.MARKET,
                volume=position,
            )
            await self.bus.publish("order:request", order)
            self._last_order_time[market] = time.monotonic()
            log.info(
                "sell_order_requested",
                market=market,
                volume=str(position),
                confidence=round(confidence, 3),
            )
            await self._notifier.notify(
                Event.SELL_SIGNAL,
                f"{market} SELL {position} (conf={confidence:.2f})",
            )

    async def _try_buy(self, market: str, *, confidence: float, source: str) -> None:
        """Attempt to place a buy order respecting cooldown and limits."""
        now = time.monotonic()
        if market in self._last_order_time and now - self._last_order_time[market] < ORDER_COOLDOWN:
            return

        if self._krw_balance <= UPBIT_MIN_ORDER_KRW:
            return

        # Use rule-based max entry amount (50,000 KRW cap)
        max_order = Decimal(str(self._rules.max_entry_krw))
        # Also respect the risk-level single order limit
        risk_max = Decimal(str(self.config.risk.max_single_order_krw))
        buy_amount = min(self._krw_balance, max_order, risk_max)

        if buy_amount < UPBIT_MIN_ORDER_KRW:
            return

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
            source=source,
        )
        await self._notifier.notify(
            Event.BUY_SIGNAL,
            f"{market} BUY {buy_amount} KRW (conf={confidence:.2f}, src={source})",
        )

    async def _refresh_balances(self) -> None:
        """Fetch current balances from Upbit, including avg_buy_price."""
        try:
            accounts = await self._rest.get_accounts()
            self._positions.clear()
            self._avg_buy_prices.clear()
            for acc in accounts:
                if acc.currency == "KRW":
                    self._krw_balance = acc.balance
                else:
                    market = f"KRW-{acc.currency}"
                    if acc.balance > 0:
                        self._positions[market] = acc.balance
                        self._avg_buy_prices[market] = acc.avg_buy_price
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
