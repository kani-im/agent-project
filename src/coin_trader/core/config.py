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


class CandleConfig(BaseModel):
    intervals: list[str] = ["1m", "5m", "15m", "1h"]


class AppConfig(BaseModel):
    upbit: UpbitConfig
    redis: RedisConfig = RedisConfig()
    risk: RiskConfig = RiskConfig()
    strategy: StrategyConfig = StrategyConfig()
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
            candle=CandleConfig(**overrides.get("candle", {})),
        )
