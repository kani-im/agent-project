"""Pydantic models for Upbit API responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class Market(BaseModel):
    market: str
    korean_name: str
    english_name: str


class Account(BaseModel):
    currency: str
    balance: Decimal
    locked: Decimal
    avg_buy_price: Decimal
    unit_currency: str


class Ticker(BaseModel):
    market: str
    trade_price: Decimal
    signed_change_rate: float
    acc_trade_volume_24h: Decimal = Field(alias="acc_trade_volume_24h")
    highest_52_week_price: Decimal
    lowest_52_week_price: Decimal
    trade_timestamp: int | None = None


class Candle(BaseModel):
    market: str
    candle_date_time_kst: str
    opening_price: Decimal
    high_price: Decimal
    low_price: Decimal
    trade_price: Decimal
    candle_acc_trade_volume: Decimal
    unit: int | None = None


class OrderbookUnit(BaseModel):
    ask_price: Decimal
    bid_price: Decimal
    ask_size: Decimal
    bid_size: Decimal


class Orderbook(BaseModel):
    market: str
    total_ask_size: Decimal
    total_bid_size: Decimal
    orderbook_units: list[OrderbookUnit]


class Order(BaseModel):
    uuid: str
    side: str
    ord_type: str
    price: Decimal | None = None
    state: str
    market: str
    volume: Decimal | None = None
    remaining_volume: Decimal | None = None
    executed_volume: Decimal | None = None
    paid_fee: Decimal | None = None
    locked: Decimal | None = None
    created_at: datetime | None = None


class OrderChance(BaseModel):
    bid_fee: Decimal
    ask_fee: Decimal
    market: dict
    bid_account: dict
    ask_account: dict
