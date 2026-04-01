"""Trading signal types and utilities."""

from __future__ import annotations

from coin_trader.core.message import Direction, SignalMessage


def weighted_combine(
    signals: list[SignalMessage],
    weights: dict[str, float],
) -> tuple[Direction, float]:
    """Combine multiple strategy signals using weighted average.

    Args:
        signals: List of signal messages from different strategies.
        weights: Weight per strategy name (e.g., {"ta": 0.4, "ml": 0.35}).

    Returns:
        Tuple of (combined direction, combined confidence).
    """
    if not signals:
        return Direction.HOLD, 0.0

    buy_score = 0.0
    sell_score = 0.0
    total_weight = 0.0

    for sig in signals:
        w = weights.get(sig.strategy, 0.0)
        if w <= 0:
            continue
        total_weight += w
        if sig.direction == Direction.BUY:
            buy_score += w * sig.confidence
        elif sig.direction == Direction.SELL:
            sell_score += w * sig.confidence
        # HOLD contributes nothing

    if total_weight == 0:
        return Direction.HOLD, 0.0

    buy_conf = buy_score / total_weight
    sell_conf = sell_score / total_weight

    if buy_conf > sell_conf:
        return Direction.BUY, buy_conf
    elif sell_conf > buy_conf:
        return Direction.SELL, sell_conf
    else:
        return Direction.HOLD, 0.0
