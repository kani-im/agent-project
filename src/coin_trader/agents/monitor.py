"""Monitor Agent - System health monitoring and alerting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from rich.console import Console
from rich.live import Live
from rich.table import Table

from coin_trader.core.base_agent import BaseAgent
from coin_trader.core.config import AppConfig
from coin_trader.core.logging import get_logger
from coin_trader.core.message import (
    AlertMessage,
    BaseMessage,
    HeartbeatMessage,
    OrderResultMessage,
    SignalMessage,
)

log = get_logger(__name__)

HEARTBEAT_TIMEOUT = 15.0  # seconds before agent is considered dead
DASHBOARD_REFRESH = 2.0


class MonitorAgent(BaseAgent):
    agent_type = "monitor"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        # agent_id -> last heartbeat time
        self._heartbeats: dict[str, float] = {}
        # agent_id -> agent_type
        self._agent_types: dict[str, str] = {}
        # Recent alerts
        self._alerts: list[dict] = []
        self._max_alerts = 50
        # Recent signals
        self._latest_signals: dict[str, SignalMessage] = {}
        # Order stats
        self._order_count: int = 0
        self._order_filled: int = 0
        self._order_failed: int = 0
        self._console = Console()

    async def setup(self) -> None:
        log.info("monitor_setup")

    async def run(self) -> None:
        # Subscribe to heartbeats
        hb_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["system:heartbeat"],
                group="monitor_hb",
                consumer=self.agent_id,
                handler=self._on_heartbeat,
            )
        )
        self._tasks.append(hb_task)

        # Subscribe to alerts
        alert_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["alert:risk"],
                group="monitor_alerts",
                consumer=self.agent_id,
                handler=self._on_alert,
            )
        )
        self._tasks.append(alert_task)

        # Subscribe to signals
        signal_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["signal:ta", "signal:ml", "signal:sentiment"],
                group="monitor_signals",
                consumer=self.agent_id,
                handler=self._on_signal,
            )
        )
        self._tasks.append(signal_task)

        # Subscribe to order results
        order_task = asyncio.create_task(
            self.bus.subscribe(
                streams=["order:filled", "order:failed"],
                group="monitor_orders",
                consumer=self.agent_id,
                handler=self._on_order_result,
            )
        )
        self._tasks.append(order_task)

        # Dashboard loop
        with Live(self._build_dashboard(), refresh_per_second=1, console=self._console) as live:
            while self._running:
                self._check_heartbeats()
                live.update(self._build_dashboard())
                await asyncio.sleep(DASHBOARD_REFRESH)

    async def _on_heartbeat(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, HeartbeatMessage):
            self._heartbeats[message.source_agent] = time.monotonic()
            self._agent_types[message.source_agent] = message.agent_type

    async def _on_alert(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, AlertMessage):
            self._alerts.append({
                "time": message.timestamp.strftime("%H:%M:%S"),
                "level": message.level,
                "title": message.title,
                "detail": message.detail,
            })
            if len(self._alerts) > self._max_alerts:
                self._alerts = self._alerts[-self._max_alerts :]
            log.warning("alert", level=message.level, title=message.title)

    async def _on_signal(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, SignalMessage):
            key = f"{message.market}:{message.strategy}"
            self._latest_signals[key] = message

    async def _on_order_result(self, stream: str, message: BaseMessage) -> None:
        if isinstance(message, OrderResultMessage):
            self._order_count += 1
            if message.status.value == "filled":
                self._order_filled += 1
            elif message.status.value == "failed":
                self._order_failed += 1

    def _check_heartbeats(self) -> None:
        """Check for agents that haven't sent heartbeats recently."""
        now = time.monotonic()
        for agent_id, last_hb in self._heartbeats.items():
            if now - last_hb > HEARTBEAT_TIMEOUT:
                agent_type = self._agent_types.get(agent_id, "unknown")
                log.warning(
                    "agent_heartbeat_timeout",
                    agent_id=agent_id,
                    agent_type=agent_type,
                )

    def _build_dashboard(self) -> Table:
        """Build a rich table for the console dashboard."""
        now = time.monotonic()

        # Main table
        table = Table(title="Coin Trader Dashboard", expand=True)

        # Agent status section
        table.add_column("Agent", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Last HB", style="yellow")

        for agent_id, last_hb in sorted(self._heartbeats.items()):
            elapsed = now - last_hb
            status = "[green]ALIVE[/green]" if elapsed < HEARTBEAT_TIMEOUT else "[red]DEAD[/red]"
            agent_type = self._agent_types.get(agent_id, "?")
            table.add_row(
                agent_id[:20],
                agent_type,
                status,
                f"{elapsed:.0f}s ago",
            )

        # Separator
        table.add_section()

        # Signal summary
        for key, sig in sorted(self._latest_signals.items()):
            color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(
                sig.direction.value, "white"
            )
            table.add_row(
                f"Signal: {key}",
                sig.direction.value,
                f"[{color}]{sig.confidence:.2f}[/{color}]",
                sig.timestamp.strftime("%H:%M:%S"),
            )

        table.add_section()

        # Order stats
        table.add_row(
            "Orders",
            f"Total: {self._order_count}",
            f"[green]Filled: {self._order_filled}[/green]",
            f"[red]Failed: {self._order_failed}[/red]",
        )

        return table
