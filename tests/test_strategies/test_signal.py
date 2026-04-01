"""Tests for strategies.signal module."""

from __future__ import annotations

from coin_trader.core.message import Direction, SignalMessage
from coin_trader.strategies.signal import weighted_combine


def _make_signal(direction: Direction, confidence: float, strategy: str) -> SignalMessage:
    return SignalMessage(
        source_agent="test",
        market="KRW-BTC",
        direction=direction,
        confidence=confidence,
        strategy=strategy,
    )


class TestWeightedCombine:
    def test_empty_signals(self) -> None:
        direction, conf = weighted_combine([], {"ta": 0.5})
        assert direction == Direction.HOLD
        assert conf == 0.0

    def test_single_buy(self) -> None:
        signals = [_make_signal(Direction.BUY, 0.9, "ta")]
        direction, conf = weighted_combine(signals, {"ta": 1.0})
        assert direction == Direction.BUY
        assert abs(conf - 0.9) < 1e-9

    def test_single_sell(self) -> None:
        signals = [_make_signal(Direction.SELL, 0.7, "ml")]
        direction, conf = weighted_combine(signals, {"ml": 1.0})
        assert direction == Direction.SELL
        assert abs(conf - 0.7) < 1e-9

    def test_hold_signal_contributes_nothing(self) -> None:
        signals = [_make_signal(Direction.HOLD, 0.5, "ta")]
        direction, conf = weighted_combine(signals, {"ta": 1.0})
        assert direction == Direction.HOLD
        assert conf == 0.0

    def test_buy_wins_over_sell(self) -> None:
        signals = [
            _make_signal(Direction.BUY, 0.9, "ta"),
            _make_signal(Direction.SELL, 0.3, "ml"),
        ]
        weights = {"ta": 0.5, "ml": 0.5}
        direction, conf = weighted_combine(signals, weights)
        assert direction == Direction.BUY

    def test_sell_wins_over_buy(self) -> None:
        signals = [
            _make_signal(Direction.BUY, 0.3, "ta"),
            _make_signal(Direction.SELL, 0.9, "ml"),
        ]
        weights = {"ta": 0.5, "ml": 0.5}
        direction, conf = weighted_combine(signals, weights)
        assert direction == Direction.SELL

    def test_equal_buy_sell_returns_hold(self) -> None:
        signals = [
            _make_signal(Direction.BUY, 0.5, "ta"),
            _make_signal(Direction.SELL, 0.5, "ml"),
        ]
        weights = {"ta": 0.5, "ml": 0.5}
        direction, conf = weighted_combine(signals, weights)
        assert direction == Direction.HOLD

    def test_unknown_strategy_ignored(self) -> None:
        signals = [_make_signal(Direction.BUY, 0.9, "unknown")]
        direction, conf = weighted_combine(signals, {"ta": 1.0})
        assert direction == Direction.HOLD

    def test_three_strategies(self) -> None:
        signals = [
            _make_signal(Direction.BUY, 0.8, "ta"),
            _make_signal(Direction.BUY, 0.7, "ml"),
            _make_signal(Direction.SELL, 0.3, "sentiment"),
        ]
        weights = {"ta": 0.4, "ml": 0.35, "sentiment": 0.25}
        direction, conf = weighted_combine(signals, weights)
        assert direction == Direction.BUY
