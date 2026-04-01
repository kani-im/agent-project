"""Tests for exchange.models module."""

from __future__ import annotations

from decimal import Decimal

from coin_trader.exchange.models import (
    Account,
    Candle,
    Market,
    Order,
    Orderbook,
    OrderbookUnit,
    Ticker,
)


class TestMarket:
    def test_parse(self) -> None:
        m = Market(market="KRW-BTC", korean_name="비트코인", english_name="Bitcoin")
        assert m.market == "KRW-BTC"


class TestAccount:
    def test_parse(self) -> None:
        acc = Account(
            currency="BTC",
            balance=Decimal("0.001"),
            locked=Decimal("0"),
            avg_buy_price=Decimal("90000000"),
            unit_currency="KRW",
        )
        assert acc.balance == Decimal("0.001")
        assert acc.currency == "BTC"


class TestTicker:
    def test_parse(self) -> None:
        t = Ticker(
            market="KRW-BTC",
            trade_price=Decimal("90000000"),
            signed_change_rate=0.025,
            acc_trade_volume_24h=Decimal("1234.5"),
            highest_52_week_price=Decimal("100000000"),
            lowest_52_week_price=Decimal("50000000"),
        )
        assert t.trade_price == Decimal("90000000")


class TestCandle:
    def test_parse(self) -> None:
        c = Candle(
            market="KRW-BTC",
            candle_date_time_kst="2025-01-01T00:00:00",
            opening_price=Decimal("89000000"),
            high_price=Decimal("91000000"),
            low_price=Decimal("88000000"),
            trade_price=Decimal("90000000"),
            candle_acc_trade_volume=Decimal("100.5"),
        )
        assert c.high_price > c.low_price


class TestOrderbook:
    def test_parse(self) -> None:
        ob = Orderbook(
            market="KRW-BTC",
            total_ask_size=Decimal("10.5"),
            total_bid_size=Decimal("12.3"),
            orderbook_units=[
                OrderbookUnit(
                    ask_price=Decimal("90100000"),
                    bid_price=Decimal("90000000"),
                    ask_size=Decimal("1.0"),
                    bid_size=Decimal("1.5"),
                )
            ],
        )
        assert ob.total_bid_size > ob.total_ask_size
        assert len(ob.orderbook_units) == 1


class TestOrder:
    def test_parse_minimal(self) -> None:
        o = Order(
            uuid="test-uuid",
            side="bid",
            ord_type="limit",
            state="wait",
            market="KRW-BTC",
        )
        assert o.uuid == "test-uuid"
        assert o.price is None

    def test_parse_full(self) -> None:
        o = Order(
            uuid="test-uuid",
            side="ask",
            ord_type="market",
            state="done",
            market="KRW-BTC",
            volume=Decimal("0.001"),
            executed_volume=Decimal("0.001"),
            paid_fee=Decimal("45"),
        )
        assert o.executed_volume == o.volume
