"""Tests for strategies.combiner module."""

from __future__ import annotations

import time
from unittest.mock import patch

from coin_trader.core.message import Direction, SignalMessage
from coin_trader.strategies.combiner import SIGNAL_TTL_SECONDS, SignalCombiner


def _make_signal(
    direction: Direction, confidence: float, strategy: str, market: str = "KRW-BTC"
) -> SignalMessage:
    return SignalMessage(
        source_agent="test",
        market=market,
        direction=direction,
        confidence=confidence,
        strategy=strategy,
    )


class TestSignalCombiner:
    def setup_method(self) -> None:
        self.combiner = SignalCombiner(
            weights={"ta": 0.4, "ml": 0.35, "sentiment": 0.25},
            min_confidence=0.65,
        )

    def test_no_signals_returns_hold(self) -> None:
        direction, conf = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.HOLD
        assert conf == 0.0

    def test_single_signal_below_threshold(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.5, "ta"))
        direction, conf = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.HOLD  # Below 0.65 threshold

    def test_single_signal_above_threshold(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta"))
        direction, conf = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.BUY

    def test_update_replaces_old_signal(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta"))
        self.combiner.update(_make_signal(Direction.SELL, 0.9, "ta"))
        direction, _ = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.SELL

    def test_multiple_strategies(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.8, "ta"))
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ml"))
        self.combiner.update(_make_signal(Direction.BUY, 0.7, "sentiment"))
        direction, conf = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.BUY
        assert conf >= 0.65

    def test_expired_signals_discarded(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta"))
        # Simulate time passage beyond TTL
        market_signals = self.combiner._signals["KRW-BTC"]
        old_time = time.monotonic() - SIGNAL_TTL_SECONDS - 10
        sig, _ = market_signals["ta"]
        market_signals["ta"] = (sig, old_time)

        direction, conf = self.combiner.evaluate("KRW-BTC")
        assert direction == Direction.HOLD

    def test_different_markets_independent(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta", "KRW-BTC"))
        self.combiner.update(_make_signal(Direction.SELL, 0.9, "ta", "KRW-ETH"))

        btc_dir, _ = self.combiner.evaluate("KRW-BTC")
        eth_dir, _ = self.combiner.evaluate("KRW-ETH")
        assert btc_dir == Direction.BUY
        assert eth_dir == Direction.SELL

    def test_clear_market(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta", "KRW-BTC"))
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta", "KRW-ETH"))
        self.combiner.clear("KRW-BTC")

        btc_dir, _ = self.combiner.evaluate("KRW-BTC")
        eth_dir, _ = self.combiner.evaluate("KRW-ETH")
        assert btc_dir == Direction.HOLD
        assert eth_dir == Direction.BUY

    def test_clear_all(self) -> None:
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta", "KRW-BTC"))
        self.combiner.update(_make_signal(Direction.BUY, 0.9, "ta", "KRW-ETH"))
        self.combiner.clear()

        btc_dir, _ = self.combiner.evaluate("KRW-BTC")
        eth_dir, _ = self.combiner.evaluate("KRW-ETH")
        assert btc_dir == Direction.HOLD
        assert eth_dir == Direction.HOLD
