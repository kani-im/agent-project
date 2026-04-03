"""Application configuration using pydantic-settings."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class UpbitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UPBIT_")

    access_key: SecretStr
    secret_key: SecretStr


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = "redis://localhost:6379/0"


class RiskConfig(BaseModel):
    max_position_ratio: float = 0.3
    max_daily_loss_krw: int = 100_000
    max_single_order_krw: int = 50_000
    max_open_positions: int = 5
    drawdown_limit: float = 0.05


class StrategyWeights(BaseModel):
    ta: float = 0.4
    ml: float = 0.35
    sentiment: float = 0.25


class StrategyConfig(BaseModel):
    target_markets: list[str] = ["KRW-BTC", "KRW-ETH"]
    min_combined_confidence: float = 0.65
    weights: StrategyWeights = StrategyWeights()


class RuleStrategyConfig(BaseModel):
    """Explicit rule-based trading strategy parameters.

    Assumptions:
    - "risen +3% over the most recent 5 minutes" is measured as
      (current_price - price_5min_ago) / price_5min_ago >= entry_rise_pct.
    - The 5-minute window uses real wall-clock ticker data, not candle close times.
    - Take-profit and stop-loss are evaluated against the Upbit-reported
      avg_buy_price for each position (volume-weighted across multiple fills).
    - max_entry_krw caps the KRW amount of a single buy order per coin.
      Multiple buys for the same coin over time are allowed (DCA-style)
      as long as each individual order <= max_entry_krw.
    """

    entry_rise_pct: float = 0.03  # +3% rise in lookback window triggers buy
    lookback_seconds: int = 300  # 5-minute lookback window
    take_profit_pct: float = 0.05  # +5% profit -> sell full position
    stop_loss_pct: float = 0.02  # -2% loss -> sell full position
    max_entry_krw: int = 50_000  # Max KRW per buy order per coin


class CandleConfig(BaseModel):
    intervals: list[str] = ["1m", "5m", "15m", "1h"]


class AppConfig(BaseModel):
    upbit: UpbitConfig
    redis: RedisConfig = RedisConfig()
    risk: RiskConfig = RiskConfig()
    strategy: StrategyConfig = StrategyConfig()
    rules: RuleStrategyConfig = RuleStrategyConfig()
    candle: CandleConfig = CandleConfig()

    @classmethod
    def load(cls, settings_path: Path | None = None) -> Self:
        """Load config from environment variables and optional TOML file."""
        upbit = UpbitConfig()
        redis = RedisConfig()

        overrides: dict = {}
        if settings_path and settings_path.exists():
            with open(settings_path, "rb") as f:
                overrides = tomllib.load(f)

        return cls(
            upbit=upbit,
            redis=redis,
            risk=RiskConfig(**overrides.get("risk", {})),
            strategy=StrategyConfig(**overrides.get("strategy", {})),
            rules=RuleStrategyConfig(**overrides.get("rules", {})),
            candle=CandleConfig(**overrides.get("candle", {})),
        )
