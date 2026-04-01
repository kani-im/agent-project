"""Async WebSocket client for Upbit real-time data."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Awaitable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from coin_trader.core.logging import get_logger

log = get_logger(__name__)

WS_URL = "wss://api.upbit.com/websocket/v1"

# Reconnection backoff: 1s, 2s, 4s, 8s, ... max 60s
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0


class UpbitWebSocketClient:
    """Upbit WebSocket client with auto-reconnection."""

    def __init__(
        self,
        types: list[str],
        codes: list[str],
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        is_only_realtime: bool = True,
    ) -> None:
        """
        Args:
            types: Data types to subscribe (e.g., ["ticker", "trade", "orderbook"]).
            codes: Market codes (e.g., ["KRW-BTC", "KRW-ETH"]).
            handler: Async callback for each received message.
            is_only_realtime: If True, only receive real-time data (no snapshot).
        """
        self._types = types
        self._codes = codes
        self._handler = handler
        self._is_only_realtime = is_only_realtime
        self._running = False
        self._ws: ClientConnection | None = None

    def _build_subscribe_message(self) -> str:
        ticket = {"ticket": uuid.uuid4().hex}
        messages: list[dict] = [ticket]
        for data_type in self._types:
            msg: dict[str, Any] = {
                "type": data_type,
                "codes": self._codes,
            }
            if self._is_only_realtime:
                msg["isOnlyRealtime"] = True
            messages.append(msg)
        messages.append({"format": "DEFAULT"})
        return json.dumps(messages)

    async def start(self) -> None:
        """Connect and start receiving messages with auto-reconnection."""
        self._running = True
        backoff = INITIAL_BACKOFF

        while self._running:
            try:
                async with websockets.connect(WS_URL, ping_interval=30) as ws:
                    self._ws = ws
                    backoff = INITIAL_BACKOFF
                    log.info("ws_connected", types=self._types, codes=self._codes)

                    await ws.send(self._build_subscribe_message())

                    async for raw_message in ws:
                        if not self._running:
                            break
                        try:
                            if isinstance(raw_message, bytes):
                                raw_message = raw_message.decode("utf-8")
                            data = json.loads(raw_message)
                            await self._handler(data)
                        except Exception:
                            log.exception("ws_message_handler_error")

            except websockets.ConnectionClosed as e:
                log.warning("ws_disconnected", code=e.code, reason=e.reason)
            except Exception:
                log.exception("ws_connection_error")

            if self._running:
                log.info("ws_reconnecting", backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)

    async def stop(self) -> None:
        """Stop the WebSocket client."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
