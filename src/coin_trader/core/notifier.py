"""Notification abstraction for trading events.

Supports pluggable backends.  Currently ships with:
- **LogNotifier** (always active) – writes every event via structlog.
- **TelegramNotifier** – sends messages to a Telegram chat via Bot API.

Usage::

    notifier = Notifier.from_config(app_config.notification)
    await notifier.notify(Event.SYSTEM_START, "All agents started")
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Protocol

import httpx

from coin_trader.core.logging import get_logger

log = get_logger(__name__)


class Event(str, Enum):
    """Canonical trading event types."""

    BUY_SIGNAL = "buy_signal"
    SELL_SIGNAL = "sell_signal"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    ORDER_FAILURE = "order_failure"
    SYSTEM_START = "system_start"
    CRITICAL_ERROR = "critical_error"


# ── Backend protocol ────────────────────────────────────────────────

class NotifierBackend(Protocol):
    async def send(self, event: Event, message: str) -> None: ...


# ── Log backend (always active) ────────────────────────────────────

class LogNotifier:
    """Logs every notification via structlog."""

    async def send(self, event: Event, message: str) -> None:
        log.info("notification", event_type=event.value, detail=message)


# ── Telegram backend ───────────────────────────────────────────────

_EMOJI: dict[Event, str] = {
    Event.BUY_SIGNAL: "\U0001f7e2",      # 🟢
    Event.SELL_SIGNAL: "\U0001f534",      # 🔴
    Event.TAKE_PROFIT: "\U0001f389",      # 🎉
    Event.STOP_LOSS: "\U0001f6a8",        # 🚨
    Event.ORDER_FAILURE: "\u26a0\ufe0f",  # ⚠️
    Event.SYSTEM_START: "\U0001f680",     # 🚀
    Event.CRITICAL_ERROR: "\U0001f4a5",   # 💥
}

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    """Sends messages to a Telegram chat via Bot API."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, event: Event, message: str) -> None:
        emoji = _EMOJI.get(event, "")
        text = f"{emoji} *[{event.value}]*\n{message}"
        try:
            client = await self._get_client()
            resp = await client.post(
                self._url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            if resp.status_code != 200:
                log.warning(
                    "telegram_send_failed",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
        except Exception:
            log.exception("telegram_send_error")


# ── Composite notifier ─────────────────────────────────────────────

class Notifier:
    """Fan-out to all configured backends.

    Failures in one backend never block others.
    """

    def __init__(self, backends: list[NotifierBackend]) -> None:
        self._backends = backends

    async def notify(self, event: Event, message: str) -> None:
        tasks = [backend.send(event, message) for backend in self._backends]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning(
                    "notifier_backend_error",
                    backend=type(self._backends[i]).__name__,
                    error=str(result),
                )

    @classmethod
    def from_config(cls, cfg) -> Notifier:
        """Build a Notifier from a NotificationConfig."""
        backends: list[NotifierBackend] = [LogNotifier()]
        if cfg.enabled and cfg.bot_token and cfg.chat_id:
            backends.append(
                TelegramNotifier(cfg.bot_token, cfg.chat_id)
            )
        return cls(backends)
