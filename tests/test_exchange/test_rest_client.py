"""Tests for exchange.rest_client module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from coin_trader.exchange.models import Account, Candle, Market, Ticker
from coin_trader.exchange.rest_client import BASE_URL, UpbitRestClient


@pytest.fixture
def client() -> UpbitRestClient:
    c = UpbitRestClient("test-key", "test-secret")
    # Bypass rate limiter for tests
    c._query_limiter.acquire = AsyncMock()
    c._order_limiter.acquire = AsyncMock()
    return c


class TestUpbitRestClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_markets(self, client: UpbitRestClient) -> None:
        respx.get(f"{BASE_URL}/market/all").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin"},
                    {"market": "KRW-ETH", "korean_name": "이더리움", "english_name": "Ethereum"},
                ],
            )
        )
        markets = await client.get_markets()
        assert len(markets) == 2
        assert all(isinstance(m, Market) for m in markets)
        assert markets[0].market == "KRW-BTC"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_ticker(self, client: UpbitRestClient) -> None:
        respx.get(f"{BASE_URL}/ticker").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "market": "KRW-BTC",
                        "trade_price": 90000000,
                        "signed_change_rate": 0.025,
                        "acc_trade_volume_24h": 1234.5,
                        "highest_52_week_price": 100000000,
                        "lowest_52_week_price": 50000000,
                    }
                ],
            )
        )
        tickers = await client.get_ticker(["KRW-BTC"])
        assert len(tickers) == 1
        assert tickers[0].trade_price == Decimal("90000000")

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_candles_minutes(self, client: UpbitRestClient) -> None:
        respx.get(f"{BASE_URL}/candles/minutes/1").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "market": "KRW-BTC",
                        "candle_date_time_kst": "2025-01-01T00:01:00",
                        "opening_price": 89000000,
                        "high_price": 89500000,
                        "low_price": 88500000,
                        "trade_price": 89200000,
                        "candle_acc_trade_volume": 5.5,
                    }
                ],
            )
        )
        candles = await client.get_candles_minutes("KRW-BTC", unit=1, count=1)
        assert len(candles) == 1
        assert isinstance(candles[0], Candle)

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_accounts(self, client: UpbitRestClient) -> None:
        respx.get(f"{BASE_URL}/accounts").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "currency": "KRW",
                        "balance": "1000000",
                        "locked": "0",
                        "avg_buy_price": "0",
                        "unit_currency": "KRW",
                    }
                ],
            )
        )
        accounts = await client.get_accounts()
        assert len(accounts) == 1
        assert accounts[0].currency == "KRW"
        assert accounts[0].balance == Decimal("1000000")

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_order(self, client: UpbitRestClient) -> None:
        respx.post(f"{BASE_URL}/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "uuid": "order-123",
                    "side": "bid",
                    "ord_type": "market",
                    "state": "wait",
                    "market": "KRW-BTC",
                },
            )
        )
        order = await client.create_order(
            market="KRW-BTC", side="bid", ord_type="market", price=Decimal("50000")
        )
        assert order.uuid == "order-123"

    @pytest.mark.asyncio
    async def test_close(self, client: UpbitRestClient) -> None:
        await client.close()
        # Should not raise on double close
