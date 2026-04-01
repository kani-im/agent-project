"""Tests for exchange.rate_limiter module."""

from __future__ import annotations

import asyncio
import time

import pytest

from coin_trader.exchange.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_burst(self) -> None:
        limiter = RateLimiter(rate=10.0, burst=5)
        # Should acquire 5 tokens immediately (burst capacity)
        for _ in range(5):
            await limiter.acquire()
        # Tokens should be exhausted
        assert limiter._tokens < 1.0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self) -> None:
        limiter = RateLimiter(rate=100.0, burst=1)
        await limiter.acquire()  # Use the one token

        start = time.monotonic()
        await limiter.acquire()  # Should wait for refill
        elapsed = time.monotonic() - start
        assert elapsed > 0.005  # Had to wait at least a tiny bit

    @pytest.mark.asyncio
    async def test_refill(self) -> None:
        limiter = RateLimiter(rate=1000.0, burst=10)
        # Drain all tokens
        for _ in range(10):
            await limiter.acquire()

        # Wait for some refill
        await asyncio.sleep(0.02)
        limiter._refill()
        assert limiter._tokens > 0

    def test_refill_does_not_exceed_burst(self) -> None:
        limiter = RateLimiter(rate=100.0, burst=5)
        # Manually set last refill to far in the past
        limiter._last_refill = time.monotonic() - 100
        limiter._refill()
        assert limiter._tokens == 5.0  # Capped at burst
