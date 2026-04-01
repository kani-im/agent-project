"""Sentiment Strategy Agent - Market sentiment analysis from orderbook and volume."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from decimal import Decimal

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    BaseMessage,
    Direction,
    OrderbookMessage,
    SignalMessage,
    TickerMessage,
)

log = get_logger(__name__)

EVAL_INTERVAL = 15.0
VOLUME_HISTORY_SIZE = 60  # Keep last 60 ticks for volume spike detection


class StrategySentimentAgent(BaseAgent):
    agent_type = "strategy_sentiment"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        # market -> latest orderbook snapshot
        self._orderbooks: dict[str, OrderbookMessage] = {}
        # market -> recent trade volumes
        self._volumes: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=VOLUME_HISTORY_SIZE)
        )
        # market -> recent prices
        self._prices: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=VOLUME_HISTORY_SIZE)
        )

    async def setup(self) -> None:
        log.info("strategy_sentiment_setup")

    async def run(self) -> None:
        markets = self.config.strategy.target_markets
        streams = []
        for m in markets:
            streams.append(f"market:ticker:{m}")
            streams.append(f"market:orderbook:{m}")

        subscribe_task = asyncio.create_task(
            self.bus.subscribe(
                streams=streams,
                group="strategy_sentiment",
                consumer=self.agent_id,
                handler=self._on_message,
            )
        )
        self._tasks.append(subscribe_task)

        while self._running:
            for market in markets:
                await self._evaluate(market)
            await asyncio.sleep(EVAL_INTERVAL)

    async def _on_message(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, OrderbookMessage):
            self._orderbooks[message.market] = message
        elif isinstance(message, TickerMessage):
            self._volumes[message.market].append(
                float(message.acc_trade_volume_24h)
            )
            self._prices[message.market].append(float(message.trade_price))

    async def _evaluate(self, market: str) -> None:
        scores: list[float] = []
        metadata: dict = {}

        # 1. Orderbook imbalance (bid/ask ratio)
        ob = self._orderbooks.get(market)
        if ob:
            total_bid = float(ob.total_bid_size)
            total_ask = float(ob.total_ask_size)
            if total_ask > 0:
                bid_ask_ratio = total_bid / total_ask
                metadata["bid_ask_ratio"] = round(bid_ask_ratio, 3)
                if bid_ask_ratio > 1.5:
                    scores.append(0.7)  # Strong buying pressure
                elif bid_ask_ratio > 1.1:
                    scores.append(0.3)
                elif bid_ask_ratio < 0.67:
                    scores.append(-0.7)  # Strong selling pressure
                elif bid_ask_ratio < 0.9:
                    scores.append(-0.3)
                else:
                    scores.append(0.0)

        # 2. Volume spike detection
        volumes = list(self._volumes.get(market, []))
        if len(volumes) >= 10:
            recent_avg = sum(volumes[-5:]) / 5
            older_avg = sum(volumes[-10:-5]) / 5
            if older_avg > 0:
                vol_change = (recent_avg - older_avg) / older_avg
                metadata["volume_change"] = round(vol_change, 3)
                if vol_change > 0.5:
                    scores.append(0.5)  # Volume surge (potential momentum)
                elif vol_change > 0.2:
                    scores.append(0.2)

        # 3. Price momentum (short-term)
        prices = list(self._prices.get(market, []))
        if len(prices) >= 5:
            recent_price = prices[-1]
            past_price = prices[-5]
            if past_price > 0:
                price_change = (recent_price - past_price) / past_price
                metadata["price_momentum"] = round(price_change, 5)
                if price_change > 0.005:
                    scores.append(0.4)
                elif price_change < -0.005:
                    scores.append(-0.4)

        if not scores:
            return

        avg_score = sum(scores) / len(scores)

        if avg_score > 0.1:
            direction = Direction.BUY
        elif avg_score < -0.1:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD

        confidence = min(abs(avg_score), 1.0)

        signal = SignalMessage(
            source_agent=self.agent_id,
            market=market,
            direction=direction,
            confidence=confidence,
            strategy="sentiment",
            metadata=metadata,
        )
        await self.bus.publish("signal:sentiment", signal)
        log.debug(
            "sentiment_signal",
            market=market,
            direction=direction.value,
            confidence=round(confidence, 3),
        )
