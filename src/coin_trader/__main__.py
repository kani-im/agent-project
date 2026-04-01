"""CLI entrypoint for Coin Trader."""

from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console

from coin_trader.core.config import AppConfig
from coin_trader.core.logging import setup_logging

app = typer.Typer(name="coin-trader", help="Multi-agent crypto trading system for Upbit")
console = Console()

DEFAULT_SETTINGS = Path("config/settings.toml")


class AgentName(str, Enum):
    all = "all"
    data_collector = "data_collector"
    strategy_ta = "strategy_ta"
    strategy_ml = "strategy_ml"
    strategy_sentiment = "strategy_sentiment"
    risk_manager = "risk_manager"
    executor = "executor"
    portfolio_manager = "portfolio_manager"
    monitor = "monitor"


def _get_agent_class(name: str):
    """Lazily import and return agent class."""
    from coin_trader.agents.data_collector import DataCollectorAgent
    from coin_trader.agents.executor import ExecutorAgent
    from coin_trader.agents.monitor import MonitorAgent
    from coin_trader.agents.portfolio_manager import PortfolioManagerAgent
    from coin_trader.agents.risk_manager import RiskManagerAgent
    from coin_trader.agents.strategy_ml import StrategyMLAgent
    from coin_trader.agents.strategy_sentiment import StrategySentimentAgent
    from coin_trader.agents.strategy_ta import StrategyTAAgent

    return {
        "data_collector": DataCollectorAgent,
        "strategy_ta": StrategyTAAgent,
        "strategy_ml": StrategyMLAgent,
        "strategy_sentiment": StrategySentimentAgent,
        "risk_manager": RiskManagerAgent,
        "executor": ExecutorAgent,
        "portfolio_manager": PortfolioManagerAgent,
        "monitor": MonitorAgent,
    }[name]


# Recommended startup order
AGENT_ORDER = [
    "data_collector",
    "strategy_ta",
    "strategy_ml",
    "strategy_sentiment",
    "risk_manager",
    "executor",
    "portfolio_manager",
    "monitor",
]


@app.command()
def run(
    agent: AgentName = typer.Argument(
        AgentName.all, help="Which agent to run (or 'all')"
    ),
    settings: Path = typer.Option(
        DEFAULT_SETTINGS, "--settings", "-s", help="Path to settings.toml"
    ),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Log level"),
) -> None:
    """Run one or all trading agents."""
    setup_logging(log_level)
    config = AppConfig.load(settings)

    if agent == AgentName.all:
        console.print("[bold green]Starting all agents...[/bold green]")
        asyncio.run(_run_all_agents(config))
    else:
        console.print(f"[bold green]Starting agent: {agent.value}[/bold green]")
        agent_cls = _get_agent_class(agent.value)
        instance = agent_cls(config)
        asyncio.run(instance.start())


async def _run_all_agents(config: AppConfig) -> None:
    """Run all agents concurrently."""
    agents = []
    for name in AGENT_ORDER:
        agent_cls = _get_agent_class(name)
        agents.append(agent_cls(config))

    tasks = [asyncio.create_task(agent.start()) for agent in agents]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        for agent in agents:
            await agent.shutdown()


@app.command()
def status(
    settings: Path = typer.Option(
        DEFAULT_SETTINGS, "--settings", "-s", help="Path to settings.toml"
    ),
) -> None:
    """Check system status by reading Redis heartbeats."""
    import time

    import redis

    setup_logging("WARNING")
    config = AppConfig.load(settings)

    r = redis.from_url(config.redis.url)
    try:
        r.ping()
        console.print("[green]Redis: Connected[/green]")
    except redis.ConnectionError:
        console.print("[red]Redis: Not reachable[/red]")
        raise typer.Exit(1)

    # Read recent heartbeats
    try:
        messages = r.xrevrange("system:heartbeat", count=20)
        seen: dict[str, str] = {}
        for _msg_id, data in messages:
            raw = data.get(b"_data", b"")
            if raw:
                import json
                parsed = json.loads(raw)
                agent_id = parsed.get("source_agent", "?")
                agent_type = parsed.get("agent_type", "?")
                if agent_id not in seen:
                    seen[agent_id] = agent_type

        if seen:
            console.print(f"\n[bold]Active agents ({len(seen)}):[/bold]")
            for agent_id, agent_type in seen.items():
                console.print(f"  [cyan]{agent_type}[/cyan] ({agent_id})")
        else:
            console.print("[yellow]No active agents found[/yellow]")
    except Exception as e:
        console.print(f"[red]Error reading heartbeats: {e}[/red]")


if __name__ == "__main__":
    app()
