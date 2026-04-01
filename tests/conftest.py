"""Shared test fixtures."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Set dummy env vars before any config import
os.environ.setdefault("UPBIT_ACCESS_KEY", "test_access_key")
os.environ.setdefault("UPBIT_SECRET_KEY", "test_secret_key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from coin_trader.core.config import AppConfig
from coin_trader.core.message import (
    Direction,
    OrderRequestMessage,
    OrderSide,
    OrderType,
    SignalMessage,
)


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    """Minimal AppConfig for testing."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        """\
[strategy]
target_markets = ["KRW-BTC"]
min_combined_confidence = 0.65

[strategy.weights]
ta = 0.4
ml = 0.35
sentiment = 0.25

[risk]
max_position_ratio = 0.3
max_daily_loss_krw = 100000
max_single_order_krw = 50000
max_open_positions = 5
drawdown_limit = 0.05
"""
    )
    return AppConfig.load(settings)


@pytest.fixture
def sample_signal() -> SignalMessage:
    return SignalMessage(
        source_agent="test-agent",
        market="KRW-BTC",
        direction=Direction.BUY,
        confidence=0.8,
        strategy="ta",
    )


@pytest.fixture
def sample_order_request() -> OrderRequestMessage:
    return OrderRequestMessage(
        source_agent="test-agent",
        market="KRW-BTC",
        side=OrderSide.BID,
        order_type=OrderType.MARKET,
        amount_krw=Decimal("10000"),
    )


@pytest.fixture
def mock_bus() -> AsyncMock:
    """Mock RedisBus for unit testing agents."""
    bus = AsyncMock()
    bus.connect = AsyncMock()
    bus.close = AsyncMock()
    bus.publish = AsyncMock(return_value="1-0")
    bus.subscribe = AsyncMock()
    bus.ensure_group = AsyncMock()
    bus.get_latest = AsyncMock(return_value=[])
    return bus
