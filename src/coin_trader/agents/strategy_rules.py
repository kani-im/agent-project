"""Rule-Based Strategy Agent - Explicit entry/exit rules.

Buy rule:  Emit a BUY signal when a coin has risen >= +3% over the most
           recent 5 minutes (configurable via rules.entry_rise_pct /
           rules.lookback_seconds).

This agent only handles the *entry* condition.  Take-profit and stop-loss
exits are managed by the PortfolioManager because they depend on position
state (average buy price), which this agent does not track.

Assumptions
-----------
* "Most recent 5 minutes" is measured from the latest ticker price back to
  the oldest price still within the lookback window.  If no price older than
  the window exists yet (e.g. the agent just started), the check is skipped.
* The agent publishes to the ``signal:rules`` stream with strategy="rules".
  The PortfolioManager treats signals from this strategy as direct entry
  triggers (high confidence, 0.95).
* One signal per market per evaluation cycle; duplicates within the cooldown
  period are suppressed by the PortfolioManager.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from decimal import Decimal

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    BaseMessage,
    Direction,
    SignalMessage,
    TickerMessage,
)

log = get_logger(__name__)

# How often we evaluate the entry rule (seconds).
EVAL_INTERVAL = 5.0


class StrategyRulesAgent(BaseAgent):
    agent_type = "strategy_rules"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._entry_rise_pct: float = config.rules.entry_rise_pct
        self._lookback_seconds: int = config.rules.lookback_seconds
        # market -> deque of (monotonic_time, price)
        self._price_history: dict[str, deque[tuple[float, Decimal]]] = defaultdict(
            lambda: deque(maxlen=3600)  # ~1 hour at 1 tick/sec
        )

    async def setup(self) -> None:
        log.info(
            "strategy_rules_setup",
            entry_rise_pct=self._entry_rise_pct,
            lookback_seconds=self._lookback_seconds,
        )

    async def run(self) -> None:
        markets = self.config.strategy.target_markets
        ticker_streams = [f"market:ticker:{m}" for m in markets]

        ticker_task = asyncio.create_task(
            self.bus.subscribe(
                streams=ticker_streams,
                group="strategy_rules_ticker",
                consumer=self.agent_id,
                handler=self._on_ticker,
            )
        )
        self._tasks.append(ticker_task)

        while self._running:
            for market in markets:
                await self._evaluate_entry(market)
            await asyncio.sleep(EVAL_INTERVAL)

    async def _on_ticker(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, TickerMessage):
            now = time.monotonic()
            self._price_history[message.market].append(
                (now, message.trade_price)
            )

    async def _evaluate_entry(self, market: str) -> None:
        """Check if the coin has risen >= entry_rise_pct in the lookback window."""
        history = self._price_history.get(market)
        if not history or len(history) < 2:
            return

        now = time.monotonic()
        cutoff = now - self._lookback_seconds

        # Prune stale entries from the left
        while history and history[0][0] < cutoff:
            history.popleft()

        if not history:
            return

        oldest_price = history[0][1]
        latest_price = history[-1][1]

        if oldest_price <= 0:
            return

        change_pct = (latest_price - oldest_price) / oldest_price

        if change_pct >= Decimal(str(self._entry_rise_pct)):
            signal = SignalMessage(
                source_agent=self.agent_id,
                market=market,
                direction=Direction.BUY,
                confidence=0.95,
                strategy="rules",
                metadata={
                    "change_pct": float(change_pct),
                    "lookback_seconds": self._lookback_seconds,
                    "oldest_price": str(oldest_price),
                    "latest_price": str(latest_price),
                },
            )
            await self.bus.publish("signal:rules", signal)
            log.info(
                "rule_buy_signal",
                market=market,
                change_pct=f"{float(change_pct):.4f}",
                oldest_price=str(oldest_price),
                latest_price=str(latest_price),
            )
