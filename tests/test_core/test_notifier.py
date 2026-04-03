"""Tests for core.notifier module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from coin_trader.core.config import NotificationConfig
from coin_trader.core.notifier import (
    Event,
    LogNotifier,
    Notifier,
    TelegramNotifier,
)


class TestLogNotifier:
    @pytest.mark.asyncio
    async def test_send_logs_event(self) -> None:
        notifier = LogNotifier()
        # Should not raise
        await notifier.send(Event.BUY_SIGNAL, "test message")


class TestTelegramNotifier:
    @pytest.mark.asyncio
    async def test_send_posts_to_api(self) -> None:
        notifier = TelegramNotifier(bot_token="fake-token", chat_id="12345")
        mock_response = AsyncMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        notifier._client = mock_client

        await notifier.send(Event.SYSTEM_START, "Bot started")

        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["chat_id"] == "12345"
        assert "system_start" in call_kwargs[1]["json"]["text"]

    @pytest.mark.asyncio
    async def test_send_handles_failure_gracefully(self) -> None:
        notifier = TelegramNotifier(bot_token="fake", chat_id="123")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("network error"))
        mock_client.is_closed = False
        notifier._client = mock_client

        # Should not raise
        await notifier.send(Event.CRITICAL_ERROR, "something broke")


class TestNotifier:
    @pytest.mark.asyncio
    async def test_fan_out_to_all_backends(self) -> None:
        backend1 = AsyncMock()
        backend2 = AsyncMock()
        notifier = Notifier(backends=[backend1, backend2])

        await notifier.notify(Event.BUY_SIGNAL, "BTC buy")

        backend1.send.assert_awaited_once_with(Event.BUY_SIGNAL, "BTC buy")
        backend2.send.assert_awaited_once_with(Event.BUY_SIGNAL, "BTC buy")

    @pytest.mark.asyncio
    async def test_backend_failure_does_not_block_others(self) -> None:
        failing = AsyncMock()
        failing.send = AsyncMock(side_effect=Exception("fail"))
        working = AsyncMock()

        notifier = Notifier(backends=[failing, working])
        await notifier.notify(Event.STOP_LOSS, "SL hit")

        working.send.assert_awaited_once()

    def test_from_config_disabled(self) -> None:
        cfg = NotificationConfig(enabled=False)
        notifier = Notifier.from_config(cfg)
        assert len(notifier._backends) == 1  # LogNotifier only

    def test_from_config_telegram_enabled(self) -> None:
        cfg = NotificationConfig(enabled=True, bot_token="tok", chat_id="123")
        notifier = Notifier.from_config(cfg)
        assert len(notifier._backends) == 2
        assert isinstance(notifier._backends[1], TelegramNotifier)

    def test_from_config_telegram_missing_token(self) -> None:
        cfg = NotificationConfig(enabled=True, bot_token="", chat_id="123")
        notifier = Notifier.from_config(cfg)
        assert len(notifier._backends) == 1  # Falls back to log only
