"""Technical Analysis Strategy Agent."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal

import pandas as pd

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import BaseMessage, CandleMessage, Direction, SignalMessage
from coin_trader.strategies.indicators import analyze_ta

log = get_logger(__name__)

# Minimum candles needed for TA calculation
MIN_CANDLES = 30

# How often to evaluate (seconds)
EVAL_INTERVAL = 10.0


class StrategyTAAgent(BaseAgent):
    agent_type = "strategy_ta"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        # market -> list of candle dicts (OHLCV)
        self._candles: dict[str, list[dict]] = defaultdict(list)
        self._max_candles = 200

    async def setup(self) -> None:
        log.info("strategy_ta_setup")

    async def run(self) -> None:
        markets = self.config.strategy.target_markets
        streams = [f"market:candle:{m}" for m in markets]

        subscribe_task = asyncio.create_task(
            self.bus.subscribe(
                streams=streams,
                group="strategy_ta",
                consumer=self.agent_id,
                handler=self._on_message,
            )
        )
        self._tasks.append(subscribe_task)

        # Periodic evaluation loop
        while self._running:
            for market in markets:
                await self._evaluate(market)
            await asyncio.sleep(EVAL_INTERVAL)

    async def _on_message(self, stream: str, message: BaseMessage) -> None:
        if not isinstance(message, CandleMessage):
            return

        candle = {
            "open": float(message.open),
            "high": float(message.high),
            "low": float(message.low),
            "close": float(message.close),
            "volume": float(message.volume),
        }

        candles = self._candles[message.market]
        candles.append(candle)
        if len(candles) > self._max_candles:
            self._candles[message.market] = candles[-self._max_candles :]

    async def _evaluate(self, market: str) -> None:
        candles = self._candles.get(market, [])
        if len(candles) < MIN_CANDLES:
            return

        df = pd.DataFrame(candles)
        try:
            indicators = analyze_ta(df)
        except Exception:
            log.exception("ta_analysis_error", market=market)
            return

        direction, confidence = self._generate_signal(indicators)

        signal = SignalMessage(
            source_agent=self.agent_id,
            market=market,
            direction=direction,
            confidence=confidence,
            strategy="ta",
            metadata=indicators,
        )
        await self.bus.publish("signal:ta", signal)
        log.debug(
            "ta_signal",
            market=market,
            direction=direction.value,
            confidence=round(confidence, 3),
        )

    def _generate_signal(self, ind: dict) -> tuple[Direction, float]:
        """Generate a trading signal from indicator values."""
        scores: list[float] = []  # positive = bullish, negative = bearish

        # RSI signal
        rsi = ind.get("rsi")
        if rsi is not None:
            if rsi < 30:
                scores.append(0.8)  # oversold -> buy
            elif rsi > 70:
                scores.append(-0.8)  # overbought -> sell
            elif rsi < 45:
                scores.append(0.3)
            elif rsi > 55:
                scores.append(-0.3)
            else:
                scores.append(0.0)

        # MACD signal
        macd_hist = ind.get("macd_histogram")
        if macd_hist is not None:
            if macd_hist > 0:
                scores.append(0.6)
            elif macd_hist < 0:
                scores.append(-0.6)

        # Bollinger Bands signal
        price = ind.get("current_price")
        bb_lower = ind.get("bb_lower")
        bb_upper = ind.get("bb_upper")
        if price and bb_lower and bb_upper:
            if price <= bb_lower:
                scores.append(0.7)  # at lower band -> buy
            elif price >= bb_upper:
                scores.append(-0.7)  # at upper band -> sell
            else:
                scores.append(0.0)

        # EMA crossover signal
        ema_short = ind.get("ema_short")
        ema_long = ind.get("ema_long")
        if ema_short is not None and ema_long is not None:
            if ema_short > ema_long:
                scores.append(0.5)
            else:
                scores.append(-0.5)

        # Volume confirmation
        vol = ind.get("current_volume")
        vol_sma = ind.get("volume_sma")
        if vol and vol_sma and vol_sma > 0:
            vol_ratio = vol / vol_sma
            if vol_ratio > 1.5:
                # High volume amplifies the signal
                for i in range(len(scores)):
                    scores[i] *= 1.2

        if not scores:
            return Direction.HOLD, 0.0

        avg_score = sum(scores) / len(scores)

        if avg_score > 0.1:
            return Direction.BUY, min(abs(avg_score), 1.0)
        elif avg_score < -0.1:
            return Direction.SELL, min(abs(avg_score), 1.0)
        else:
            return Direction.HOLD, 0.0
