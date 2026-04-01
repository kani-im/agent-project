"""Data Collector Agent - Collects market data via WebSocket and REST."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import CandleMessage, OrderbookMessage, TickerMessage
from coin_trader.exchange.rest_client import UpbitRestClient
from coin_trader.exchange.ws_client import UpbitWebSocketClient

log = get_logger(__name__)

# REST polling interval for candle history
REST_POLL_INTERVAL = 60.0


class DataCollectorAgent(BaseAgent):
    agent_type = "data_collector"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._rest: UpbitRestClient | None = None
        self._ws_clients: list[UpbitWebSocketClient] = []

    async def setup(self) -> None:
        self._rest = UpbitRestClient(
            access_key=self.config.upbit.access_key.get_secret_value(),
            secret_key=self.config.upbit.secret_key.get_secret_value(),
        )
        markets = self.config.strategy.target_markets

        # WebSocket for ticker
        self._ws_clients.append(
            UpbitWebSocketClient(
                types=["ticker"],
                codes=markets,
                handler=self._handle_ticker,
            )
        )
        # WebSocket for orderbook
        self._ws_clients.append(
            UpbitWebSocketClient(
                types=["orderbook"],
                codes=markets,
                handler=self._handle_orderbook,
            )
        )
        # WebSocket for trade (used for real-time candle building)
        self._ws_clients.append(
            UpbitWebSocketClient(
                types=["trade"],
                codes=markets,
                handler=self._handle_trade,
            )
        )

        log.info("data_collector_setup", markets=markets)

    async def run(self) -> None:
        # Start all WebSocket clients and REST polling concurrently
        tasks = [asyncio.create_task(ws.start()) for ws in self._ws_clients]
        tasks.append(asyncio.create_task(self._poll_candles()))
        self._tasks.extend(tasks)

        # Wait until shutdown
        while self._running:
            await asyncio.sleep(1)

    async def teardown(self) -> None:
        for ws in self._ws_clients:
            await ws.stop()
        if self._rest:
            await self._rest.close()

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """Process real-time ticker data from WebSocket."""
        if data.get("type") != "ticker":
            return
        msg = TickerMessage(
            source_agent=self.agent_id,
            market=data["code"],
            trade_price=Decimal(str(data["trade_price"])),
            signed_change_rate=data.get("signed_change_rate", 0.0),
            acc_trade_volume_24h=Decimal(str(data.get("acc_trade_volume_24h", 0))),
            highest_52_week_price=Decimal(
                str(data.get("highest_52_week_price", 0))
            ),
            lowest_52_week_price=Decimal(
                str(data.get("lowest_52_week_price", 0))
            ),
        )
        await self.bus.publish(f"market:ticker:{data['code']}", msg)

    async def _handle_orderbook(self, data: dict[str, Any]) -> None:
        """Process real-time orderbook data from WebSocket."""
        if data.get("type") != "orderbook":
            return
        msg = OrderbookMessage(
            source_agent=self.agent_id,
            market=data["code"],
            total_ask_size=Decimal(str(data.get("total_ask_size", 0))),
            total_bid_size=Decimal(str(data.get("total_bid_size", 0))),
            orderbook_units=data.get("orderbook_units", []),
        )
        await self.bus.publish(f"market:orderbook:{data['code']}", msg)

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """Process real-time trade data (published as ticker-like updates)."""
        if data.get("type") != "trade":
            return
        # Publish trade data as a simplified ticker update
        msg = TickerMessage(
            source_agent=self.agent_id,
            market=data["code"],
            trade_price=Decimal(str(data["trade_price"])),
            signed_change_rate=0.0,
            acc_trade_volume_24h=Decimal("0"),
            highest_52_week_price=Decimal("0"),
            lowest_52_week_price=Decimal("0"),
        )
        await self.bus.publish(f"market:ticker:{data['code']}", msg)

    async def _poll_candles(self) -> None:
        """Periodically fetch candle data via REST API."""
        markets = self.config.strategy.target_markets
        intervals = self.config.candle.intervals

        # Map interval strings to minute units
        interval_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

        while self._running:
            for market in markets:
                for interval in intervals:
                    unit = interval_minutes.get(interval)
                    if unit is None:
                        continue
                    try:
                        candles = await self._rest.get_candles_minutes(
                            market=market, unit=unit, count=5
                        )
                        for c in candles:
                            msg = CandleMessage(
                                source_agent=self.agent_id,
                                market=c.market,
                                interval=interval,
                                open=c.opening_price,
                                high=c.high_price,
                                low=c.low_price,
                                close=c.trade_price,
                                volume=c.candle_acc_trade_volume,
                                candle_datetime=datetime.fromisoformat(
                                    c.candle_date_time_kst
                                ).replace(tzinfo=timezone.utc),
                            )
                            await self.bus.publish(
                                f"market:candle:{market}", msg
                            )
                    except Exception:
                        log.exception(
                            "candle_poll_error", market=market, interval=interval
                        )
            await asyncio.sleep(REST_POLL_INTERVAL)
