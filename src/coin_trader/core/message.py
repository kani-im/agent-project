"""Message schemas for inter-agent communication via Redis Streams."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _msg_id() -> str:
    return uuid4().hex


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderSide(str, Enum):
    BID = "bid"  # 매수
    ASK = "ask"  # 매도


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BaseMessage(BaseModel):
    msg_id: str = Field(default_factory=_msg_id)
    timestamp: datetime = Field(default_factory=_utcnow)
    source_agent: str

    def to_redis(self) -> dict[str, str]:
        """Serialize to flat dict for Redis XADD."""
        return {"_type": type(self).__name__, "_data": self.model_dump_json()}

    @classmethod
    def from_redis(cls, data: dict[bytes | str, bytes | str]) -> BaseMessage:
        """Deserialize from Redis XREAD result."""
        raw = data.get("_data") or data.get(b"_data")
        if isinstance(raw, bytes):
            raw = raw.decode()
        type_name = data.get("_type") or data.get(b"_type")
        if isinstance(type_name, bytes):
            type_name = type_name.decode()
        msg_cls = _MESSAGE_TYPES.get(type_name, cls)
        return msg_cls.model_validate_json(raw)


class CandleMessage(BaseMessage):
    market: str
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    candle_datetime: datetime


class TickerMessage(BaseMessage):
    market: str
    trade_price: Decimal
    signed_change_rate: float
    acc_trade_volume_24h: Decimal
    highest_52_week_price: Decimal
    lowest_52_week_price: Decimal


class OrderbookMessage(BaseMessage):
    market: str
    total_ask_size: Decimal
    total_bid_size: Decimal
    orderbook_units: list[dict]


class SignalMessage(BaseMessage):
    market: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: str
    metadata: dict = {}


class OrderRequestMessage(BaseMessage):
    market: str
    side: OrderSide
    order_type: OrderType
    price: Decimal | None = None
    volume: Decimal | None = None
    amount_krw: Decimal | None = None


class OrderResultMessage(BaseMessage):
    order_uuid: str
    market: str
    side: OrderSide
    status: OrderStatus
    executed_volume: Decimal
    executed_price: Decimal
    fee: Decimal


class HeartbeatMessage(BaseMessage):
    agent_type: str
    status: str = "alive"


class AlertMessage(BaseMessage):
    level: Literal["info", "warning", "critical"]
    title: str
    detail: str = ""


# Registry for deserialization
_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    cls.__name__: cls
    for cls in [
        CandleMessage,
        TickerMessage,
        OrderbookMessage,
        SignalMessage,
        OrderRequestMessage,
        OrderResultMessage,
        HeartbeatMessage,
        AlertMessage,
    ]
}
