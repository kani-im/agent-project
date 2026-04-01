#!/usr/bin/env python
"""Launch all agents as separate processes for production use."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

AGENTS = [
    "data_collector",
    "strategy_ta",
    "strategy_ml",
    "strategy_sentiment",
    "risk_manager",
    "executor",
    "portfolio_manager",
    "monitor",
]


def main() -> None:
    processes: list[subprocess.Popen] = []
    shutting_down = False

    def handle_signal(signum, frame):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("\nShutting down all agents...")
        for proc in processes:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Starting {len(AGENTS)} agents...")
    for agent_name in AGENTS:
        cmd = [sys.executable, "-m", "coin_trader", "run", agent_name]
        proc = subprocess.Popen(cmd)
        processes.append(proc)
        print(f"  Started {agent_name} (PID: {proc.pid})")
        time.sleep(0.5)  # Stagger startups

    print("\nAll agents started. Press Ctrl+C to stop.")

    # Wait for all processes
    while not shutting_down:
        for i, proc in enumerate(processes):
            if proc.poll() is not None:
                agent_name = AGENTS[i]
                print(f"Agent {agent_name} exited with code {proc.returncode}")
                if not shutting_down:
                    print(f"Restarting {agent_name}...")
                    cmd = [sys.executable, "-m", "coin_trader", "run", agent_name]
                    processes[i] = subprocess.Popen(cmd)
        time.sleep(1)

    # Wait for graceful shutdown
    for proc in processes:
        proc.wait(timeout=10)

    print("All agents stopped.")


if __name__ == "__main__":
    main()
