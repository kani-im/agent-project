"""Tests for core.config module."""

from __future__ import annotations

import os
from pathlib import Path

from coin_trader.core.config import (
    AppConfig,
    NotificationConfig,
    RiskConfig,
    StrategyConfig,
    TradingConfig,
    TradingMode,
)


class TestTradingConfig:
    def test_defaults_to_dry_run(self) -> None:
        cfg = TradingConfig()
        assert cfg.mode == TradingMode.DRY_RUN
        assert cfg.enabled is True

    def test_mode_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("TRADING_MODE", "live")
        cfg = TradingConfig()
        assert cfg.mode == TradingMode.LIVE

    def test_kill_switch_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("TRADING_ENABLED", "false")
        cfg = TradingConfig()
        assert cfg.enabled is False


class TestNotificationConfig:
    def test_defaults_disabled(self) -> None:
        cfg = NotificationConfig()
        assert cfg.enabled is False
        assert cfg.bot_token == ""
        assert cfg.chat_id == ""

    def test_reads_telegram_env(self, monkeypatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
        cfg = NotificationConfig()
        assert cfg.bot_token == "tok123"
        assert cfg.chat_id == "456"


class TestAppConfig:
    def test_load_defaults(self) -> None:
        config = AppConfig.load(settings_path=None)
        assert "redis://localhost:6379" in config.redis.url
        assert config.risk.max_daily_loss_krw == 100_000
        assert config.strategy.weights.ta == 0.4
        # New defaults
        assert config.trading.mode == TradingMode.DRY_RUN
        assert config.trading.enabled is True
        assert config.notification.enabled is False

    def test_load_from_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "test.toml"
        toml.write_text(
            """\
[risk]
max_daily_loss_krw = 200000
max_single_order_krw = 80000

[strategy]
target_markets = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
min_combined_confidence = 0.7

[notification]
enabled = true
"""
        )
        config = AppConfig.load(toml)
        assert config.risk.max_daily_loss_krw == 200_000
        assert config.risk.max_single_order_krw == 80_000
        assert len(config.strategy.target_markets) == 3
        assert config.strategy.min_combined_confidence == 0.7
        assert config.notification.enabled is True

    def test_load_nonexistent_file(self) -> None:
        config = AppConfig.load(Path("/nonexistent/settings.toml"))
        assert config.risk.max_daily_loss_krw == 100_000

    def test_risk_defaults(self) -> None:
        risk = RiskConfig()
        assert risk.max_position_ratio == 0.3
        assert risk.drawdown_limit == 0.05
        assert risk.max_open_positions == 5

    def test_strategy_weights_sum(self) -> None:
        config = StrategyConfig()
        total = config.weights.ta + config.weights.ml + config.weights.sentiment
        assert abs(total - 1.0) < 1e-9
