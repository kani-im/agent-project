"""Async REST client for Upbit API."""

from __future__ import annotations

from decimal import Decimal

import httpx

from coin_trader.core.logging import get_logger
from coin_trader.exchange.auth import create_token
from coin_trader.exchange.models import (
    Account,
    Candle,
    Market,
    Order,
    OrderChance,
    Orderbook,
    Ticker,
)
from coin_trader.exchange.rate_limiter import RateLimiter

log = get_logger(__name__)

BASE_URL = "https://api.upbit.com/v1"


class UpbitRestClient:
    """Async Upbit REST API client with rate limiting and auth."""

    def __init__(self, access_key: str, secret_key: str) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=10.0,
            headers={"Accept": "application/json"},
        )
        self._query_limiter = RateLimiter(rate=25.0, burst=25)
        self._order_limiter = RateLimiter(rate=8.0, burst=8)

    async def close(self) -> None:
        await self._client.aclose()

    def _auth_header(self, query: dict | None = None) -> dict[str, str]:
        token = create_token(self._access_key, self._secret_key, query)
        return {"Authorization": f"Bearer {token}"}

    async def _get(
        self, path: str, params: dict | None = None, auth: bool = False
    ) -> list | dict:
        await self._query_limiter.acquire()
        headers = self._auth_header(params) if auth else {}
        resp = await self._client.get(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        await self._order_limiter.acquire()
        headers = self._auth_header(body)
        resp = await self._client.post(path, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, params: dict) -> dict:
        await self._order_limiter.acquire()
        headers = self._auth_header(params)
        resp = await self._client.delete(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── Market data (public) ──

    async def get_markets(self) -> list[Market]:
        data = await self._get("/market/all")
        return [Market(**item) for item in data]

    async def get_ticker(self, markets: list[str]) -> list[Ticker]:
        params = {"markets": ",".join(markets)}
        data = await self._get("/ticker", params)
        return [Ticker(**item) for item in data]

    async def get_candles_minutes(
        self, market: str, unit: int = 1, count: int = 200
    ) -> list[Candle]:
        params = {"market": market, "count": str(count)}
        data = await self._get(f"/candles/minutes/{unit}", params)
        return [Candle(**item) for item in data]

    async def get_candles_days(
        self, market: str, count: int = 200
    ) -> list[Candle]:
        params = {"market": market, "count": str(count)}
        data = await self._get("/candles/days", params)
        return [Candle(**item) for item in data]

    async def get_orderbook(self, markets: list[str]) -> list[Orderbook]:
        params = {"markets": ",".join(markets)}
        data = await self._get("/orderbook", params)
        return [Orderbook(**item) for item in data]

    # ── Account (private) ──

    async def get_accounts(self) -> list[Account]:
        data = await self._get("/accounts", auth=True)
        return [Account(**item) for item in data]

    async def get_order_chance(self, market: str) -> OrderChance:
        params = {"market": market}
        data = await self._get("/orders/chance", params, auth=True)
        return OrderChance(**data)

    # ── Orders (private) ──

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: Decimal | None = None,
        price: Decimal | None = None,
        identifier: str | None = None,
    ) -> Order:
        body: dict = {
            "market": market,
            "side": side,
            "ord_type": ord_type,
        }
        if volume is not None:
            body["volume"] = str(volume)
        if price is not None:
            body["price"] = str(price)
        if identifier is not None:
            body["identifier"] = identifier
        data = await self._post("/orders", body)
        return Order(**data)

    async def get_order(self, uuid: str) -> Order:
        params = {"uuid": uuid}
        data = await self._get("/order", params, auth=True)
        return Order(**data)

    async def get_orders(
        self, market: str | None = None, states: list[str] | None = None
    ) -> list[Order]:
        params: dict = {}
        if market:
            params["market"] = market
        if states:
            params["states"] = states
        data = await self._get("/orders", params, auth=True)
        return [Order(**item) for item in data]

    async def cancel_order(self, uuid: str) -> Order:
        params = {"uuid": uuid}
        data = await self._delete("/order", params)
        return Order(**data)
