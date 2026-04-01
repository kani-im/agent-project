"""Tests for core.message module."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from coin_trader.core.message import (
    AlertMessage,
    BaseMessage,
    CandleMessage,
    Direction,
    HeartbeatMessage,
    OrderRequestMessage,
    OrderResultMessage,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalMessage,
    TickerMessage,
)


class TestBaseMessage:
    def test_msg_id_auto_generated(self) -> None:
        msg = HeartbeatMessage(source_agent="test", agent_type="test")
        assert msg.msg_id  # non-empty
        assert len(msg.msg_id) == 32  # uuid hex

    def test_timestamp_auto_set(self) -> None:
        msg = HeartbeatMessage(source_agent="test", agent_type="test")
        assert msg.timestamp.tzinfo == timezone.utc

    def test_unique_ids(self) -> None:
        m1 = HeartbeatMessage(source_agent="a", agent_type="a")
        m2 = HeartbeatMessage(source_agent="b", agent_type="b")
        assert m1.msg_id != m2.msg_id


class TestSerialization:
    def test_to_redis_contains_type_and_data(self) -> None:
        msg = HeartbeatMessage(source_agent="test", agent_type="monitor")
        redis_dict = msg.to_redis()
        assert redis_dict["_type"] == "HeartbeatMessage"
        assert "_data" in redis_dict

    def test_roundtrip_heartbeat(self) -> None:
        original = HeartbeatMessage(source_agent="agent-1", agent_type="monitor")
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, HeartbeatMessage)
        assert restored.source_agent == "agent-1"
        assert restored.agent_type == "monitor"
        assert restored.msg_id == original.msg_id

    def test_roundtrip_signal(self) -> None:
        original = SignalMessage(
            source_agent="ta-agent",
            market="KRW-BTC",
            direction=Direction.BUY,
            confidence=0.85,
            strategy="ta",
            metadata={"rsi": 30},
        )
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, SignalMessage)
        assert restored.direction == Direction.BUY
        assert restored.confidence == 0.85
        assert restored.metadata == {"rsi": 30}

    def test_roundtrip_candle(self) -> None:
        now = datetime.now(timezone.utc)
        original = CandleMessage(
            source_agent="dc",
            market="KRW-ETH",
            interval="5m",
            open=Decimal("5000000"),
            high=Decimal("5100000"),
            low=Decimal("4900000"),
            close=Decimal("5050000"),
            volume=Decimal("123.456"),
            candle_datetime=now,
        )
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, CandleMessage)
        assert restored.close == Decimal("5050000")
        assert restored.interval == "5m"

    def test_roundtrip_order_request(self) -> None:
        original = OrderRequestMessage(
            source_agent="pm",
            market="KRW-BTC",
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            amount_krw=Decimal("50000"),
        )
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, OrderRequestMessage)
        assert restored.side == OrderSide.BID
        assert restored.amount_krw == Decimal("50000")

    def test_roundtrip_order_result(self) -> None:
        original = OrderResultMessage(
            source_agent="exec",
            order_uuid="abc-123",
            market="KRW-BTC",
            side=OrderSide.BID,
            status=OrderStatus.FILLED,
            executed_volume=Decimal("0.001"),
            executed_price=Decimal("90000000"),
            fee=Decimal("45"),
        )
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, OrderResultMessage)
        assert restored.status == OrderStatus.FILLED

    def test_roundtrip_alert(self) -> None:
        original = AlertMessage(
            source_agent="risk",
            level="critical",
            title="Drawdown exceeded",
            detail="5.2% drawdown > 5% limit",
        )
        redis_dict = original.to_redis()
        restored = BaseMessage.from_redis(redis_dict)
        assert isinstance(restored, AlertMessage)
        assert restored.level == "critical"

    def test_from_redis_bytes_keys(self) -> None:
        msg = HeartbeatMessage(source_agent="test", agent_type="test")
        redis_dict = msg.to_redis()
        # Simulate what Redis returns: bytes keys and values
        bytes_dict = {
            b"_type": redis_dict["_type"].encode(),
            b"_data": redis_dict["_data"].encode(),
        }
        restored = BaseMessage.from_redis(bytes_dict)
        assert isinstance(restored, HeartbeatMessage)

    def test_unknown_type_falls_back_to_base(self) -> None:
        msg = HeartbeatMessage(source_agent="test", agent_type="test")
        redis_dict = msg.to_redis()
        redis_dict["_type"] = "UnknownMessage"
        restored = BaseMessage.from_redis(redis_dict)
        # Falls back to BaseMessage
        assert restored.source_agent == "test"


class TestSignalMessage:
    def test_confidence_bounds(self) -> None:
        import pytest

        with pytest.raises(Exception):
            SignalMessage(
                source_agent="a",
                market="KRW-BTC",
                direction=Direction.BUY,
                confidence=1.5,
                strategy="ta",
            )

    def test_direction_enum(self) -> None:
        assert Direction.BUY.value == "BUY"
        assert Direction.SELL.value == "SELL"
        assert Direction.HOLD.value == "HOLD"


class TestTickerMessage:
    def test_decimal_fields(self) -> None:
        msg = TickerMessage(
            source_agent="dc",
            market="KRW-BTC",
            trade_price=Decimal("90000000"),
            signed_change_rate=0.025,
            acc_trade_volume_24h=Decimal("1234.5"),
            highest_52_week_price=Decimal("100000000"),
            lowest_52_week_price=Decimal("50000000"),
        )
        assert msg.trade_price == Decimal("90000000")
        assert isinstance(msg.signed_change_rate, float)
