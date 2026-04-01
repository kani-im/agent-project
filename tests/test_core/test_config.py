"""Tests for core.config module."""

from __future__ import annotations

from pathlib import Path

from coin_trader.core.config import AppConfig, RiskConfig, StrategyConfig


class TestAppConfig:
    def test_load_defaults(self) -> None:
        config = AppConfig.load(settings_path=None)
        # Redis URL comes from env var (set in conftest)
        assert "redis://localhost:6379" in config.redis.url
        assert config.risk.max_daily_loss_krw == 100_000
        assert config.strategy.weights.ta == 0.4

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
"""
        )
        config = AppConfig.load(toml)
        assert config.risk.max_daily_loss_krw == 200_000
        assert config.risk.max_single_order_krw == 80_000
        assert len(config.strategy.target_markets) == 3
        assert config.strategy.min_combined_confidence == 0.7

    def test_load_nonexistent_file(self) -> None:
        config = AppConfig.load(Path("/nonexistent/settings.toml"))
        # Should fall back to defaults
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
