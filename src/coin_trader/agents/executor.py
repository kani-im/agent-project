"""Executor Agent - Executes approved orders on Upbit.

Respects the global trading mode:
- DRY_RUN: logs what *would* be executed, publishes a synthetic FILLED result.
- LIVE: places real orders on the exchange.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig, TradingMode
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    BaseMessage,
    OrderRequestMessage,
    OrderResultMessage,
    OrderSide,
    OrderStatus,
    OrderType,
)
from coin_trader.core.notifier import Event, Notifier
from coin_trader.exchange.rest_client import UpbitRestClient

log = get_logger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2.0
ORDER_POLL_INTERVAL = 1.0
ORDER_TIMEOUT = 60.0  # seconds to wait for order fill


class ExecutorAgent(BaseAgent):
    agent_type = "executor"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._rest: UpbitRestClient | None = None
        self._pending_orders: set[str] = set()
        self._notifier = Notifier.from_config(config.notification)
        self._dry_run = config.trading.mode == TradingMode.DRY_RUN

    async def setup(self) -> None:
        self._rest = UpbitRestClient(
            access_key=self.config.upbit.access_key.get_secret_value(),
            secret_key=self.config.upbit.secret_key.get_secret_value(),
        )
        mode_label = "DRY_RUN" if self._dry_run else "LIVE"
        log.info("executor_setup", trading_mode=mode_label)
        await self._notifier.notify(
            Event.SYSTEM_START,
            f"Executor started (mode={mode_label})",
        )

    async def run(self) -> None:
        subscribe_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["order:approved"],
                group="executor",
                consumer=self.agent_id,
                handler=self._on_approved_order,
            )
        )
        self._tasks.append(subscribe_task)

        while self._running:
            await asyncio.sleep(1)

    async def teardown(self) -> None:
        # Cancel all pending orders on shutdown
        if self._rest and self._pending_orders:
            log.info("cancelling_pending_orders", count=len(self._pending_orders))
            for order_uuid in list(self._pending_orders):
                try:
                    await self._rest.cancel_order(order_uuid)
                    log.info("order_cancelled_on_shutdown", uuid=order_uuid)
                except Exception:
                    log.exception("cancel_error_on_shutdown", uuid=order_uuid)

        if self._rest:
            await self._rest.close()

    async def _on_approved_order(self, stream: str, message: BaseMessage) -> None:
        if not isinstance(message, OrderRequestMessage):
            return
        await self._execute_order(message)

    async def _execute_order(self, order: OrderRequestMessage) -> None:
        """Execute an order with retry logic.

        In DRY_RUN mode the order is logged but never sent to the exchange.
        """
        if self._dry_run:
            log.info(
                "dry_run_order",
                market=order.market,
                side=order.side.value,
                amount_krw=str(order.amount_krw),
                volume=str(order.volume),
            )
            synthetic = OrderResultMessage(
                source_agent=self.agent_id,
                order_uuid="dry-run",
                market=order.market,
                side=order.side,
                status=OrderStatus.FILLED,
                executed_volume=order.volume or Decimal("0"),
                executed_price=order.price or Decimal("0"),
                fee=Decimal("0"),
            )
            await self.bus.publish("order:filled", synthetic)
            return

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await self._place_order(order)
                if result:
                    await self.bus.publish("order:filled", result)
                    return
            except Exception:
                log.exception(
                    "order_execution_error",
                    market=order.market,
                    attempt=attempt,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)

        # All retries failed
        fail_msg = OrderResultMessage(
            source_agent=self.agent_id,
            order_uuid="",
            market=order.market,
            side=order.side,
            status=OrderStatus.FAILED,
            executed_volume=Decimal("0"),
            executed_price=Decimal("0"),
            fee=Decimal("0"),
        )
        await self.bus.publish("order:failed", fail_msg)
        await self._notifier.notify(
            Event.ORDER_FAILURE,
            f"Order FAILED after {MAX_RETRIES} retries: {order.market} {order.side.value}",
        )

    async def _place_order(self, order: OrderRequestMessage) -> OrderResultMessage | None:
        """Place an order and wait for it to fill."""
        # Map our order types to Upbit's ord_type
        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BID:
                ord_type = "price"  # 시장가 매수
            else:
                ord_type = "market"  # 시장가 매도
        else:
            ord_type = "limit"

        created = await self._rest.create_order(
            market=order.market,
            side=order.side.value,
            ord_type=ord_type,
            volume=order.volume,
            price=order.price or order.amount_krw,
        )

        order_uuid = created.uuid
        self._pending_orders.add(order_uuid)
        log.info(
            "order_placed",
            uuid=order_uuid,
            market=order.market,
            side=order.side.value,
            type=ord_type,
        )

        # Poll for completion
        elapsed = 0.0
        while elapsed < ORDER_TIMEOUT:
            await asyncio.sleep(ORDER_POLL_INTERVAL)
            elapsed += ORDER_POLL_INTERVAL

            status = await self._rest.get_order(order_uuid)

            if status.state == "done":
                self._pending_orders.discard(order_uuid)
                return OrderResultMessage(
                    source_agent=self.agent_id,
                    order_uuid=order_uuid,
                    market=order.market,
                    side=order.side,
                    status=OrderStatus.FILLED,
                    executed_volume=status.executed_volume or Decimal("0"),
                    executed_price=status.price or Decimal("0"),
                    fee=status.paid_fee or Decimal("0"),
                )
            elif status.state == "cancel":
                self._pending_orders.discard(order_uuid)
                return OrderResultMessage(
                    source_agent=self.agent_id,
                    order_uuid=order_uuid,
                    market=order.market,
                    side=order.side,
                    status=OrderStatus.CANCELLED,
                    executed_volume=status.executed_volume or Decimal("0"),
                    executed_price=status.price or Decimal("0"),
                    fee=status.paid_fee or Decimal("0"),
                )

        # Timeout - cancel the order
        log.warning("order_timeout", uuid=order_uuid)
        try:
            await self._rest.cancel_order(order_uuid)
        except Exception:
            log.exception("order_cancel_error", uuid=order_uuid)

        self._pending_orders.discard(order_uuid)
        return None
