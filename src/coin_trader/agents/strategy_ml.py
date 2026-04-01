"""ML Strategy Agent - Machine learning based price prediction."""

from __future__ import annotations

import asyncio
from collections import defaultdict

import pandas as pd

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import BaseMessage, CandleMessage, Direction, SignalMessage
from coin_trader.strategies.ml_model import PriceDirectionModel

log = get_logger(__name__)

# Retrain interval in seconds
RETRAIN_INTERVAL = 3600.0  # 1 hour

# Prediction interval in seconds
PREDICT_INTERVAL = 30.0

MIN_CANDLES_FOR_PREDICTION = 50


class StrategyMLAgent(BaseAgent):
    agent_type = "strategy_ml"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._candles: dict[str, list[dict]] = defaultdict(list)
        self._models: dict[str, PriceDirectionModel] = {}
        self._max_candles = 500

    async def setup(self) -> None:
        for market in self.config.strategy.target_markets:
            self._models[market] = PriceDirectionModel()
        log.info("strategy_ml_setup", markets=list(self._models.keys()))

    async def run(self) -> None:
        markets = self.config.strategy.target_markets
        streams = [f"market:candle:{m}" for m in markets]

        subscribe_task = asyncio.create_task(
            self.bus.subscribe(
                streams=streams,
                group="strategy_ml",
                consumer=self.agent_id,
                handler=self._on_message,
            )
        )
        self._tasks.append(subscribe_task)

        retrain_task = asyncio.create_task(self._retrain_loop())
        self._tasks.append(retrain_task)

        # Prediction loop
        while self._running:
            for market in markets:
                await self._predict(market)
            await asyncio.sleep(PREDICT_INTERVAL)

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

    async def _retrain_loop(self) -> None:
        """Periodically retrain models with accumulated data."""
        while self._running:
            for market, model in self._models.items():
                candles = self._candles.get(market, [])
                if len(candles) >= 100:
                    df = pd.DataFrame(candles)
                    try:
                        model.train(df)
                    except Exception:
                        log.exception("ml_train_error", market=market)
            await asyncio.sleep(RETRAIN_INTERVAL)

    async def _predict(self, market: str) -> None:
        model = self._models.get(market)
        if not model or not model.is_trained:
            return

        candles = self._candles.get(market, [])
        if len(candles) < MIN_CANDLES_FOR_PREDICTION:
            return

        df = pd.DataFrame(candles)
        try:
            direction_int, confidence = model.predict(df)
        except Exception:
            log.exception("ml_predict_error", market=market)
            return

        if direction_int == 1:
            direction = Direction.BUY
        elif direction_int == -1:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD

        signal = SignalMessage(
            source_agent=self.agent_id,
            market=market,
            direction=direction,
            confidence=confidence,
            strategy="ml",
            metadata={"prediction": direction_int},
        )
        await self.bus.publish("signal:ml", signal)
        log.debug(
            "ml_signal",
            market=market,
            direction=direction.value,
            confidence=round(confidence, 3),
        )
