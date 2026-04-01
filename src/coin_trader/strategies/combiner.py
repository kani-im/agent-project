"""Signal combiner for the portfolio manager."""

from __future__ import annotations

from collections import defaultdict
import time

from coin_trader.core.message import Direction, SignalMessage
from coin_trader.strategies.signal import weighted_combine

# Signals older than this are discarded
SIGNAL_TTL_SECONDS = 120.0


class SignalCombiner:
    """Collects signals from multiple strategies and combines them."""

    def __init__(self, weights: dict[str, float], min_confidence: float) -> None:
        self._weights = weights
        self._min_confidence = min_confidence
        # market -> strategy -> (signal, receive_time)
        self._signals: dict[str, dict[str, tuple[SignalMessage, float]]] = defaultdict(
            dict
        )

    def update(self, signal: SignalMessage) -> None:
        """Register or update a signal from a strategy."""
        self._signals[signal.market][signal.strategy] = (signal, time.monotonic())

    def evaluate(self, market: str) -> tuple[Direction, float]:
        """Combine latest signals for a market.

        Returns (direction, confidence). Returns HOLD if insufficient signals
        or confidence below threshold.
        """
        now = time.monotonic()
        market_signals = self._signals.get(market, {})

        # Collect fresh signals
        fresh: list[SignalMessage] = []
        expired_keys: list[str] = []
        for strategy, (sig, ts) in market_signals.items():
            if now - ts > SIGNAL_TTL_SECONDS:
                expired_keys.append(strategy)
            else:
                fresh.append(sig)

        # Clean expired
        for key in expired_keys:
            del market_signals[key]

        if not fresh:
            return Direction.HOLD, 0.0

        direction, confidence = weighted_combine(fresh, self._weights)

        if confidence < self._min_confidence:
            return Direction.HOLD, confidence

        return direction, confidence

    def clear(self, market: str | None = None) -> None:
        """Clear signals for a market or all markets."""
        if market:
            self._signals.pop(market, None)
        else:
            self._signals.clear()
