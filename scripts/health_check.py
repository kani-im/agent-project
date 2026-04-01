#!/usr/bin/env python
"""Quick health check for the trading system."""

from __future__ import annotations

import json
import sys
import time

import redis


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "redis://localhost:6379/0"

    r = redis.from_url(url)

    # 1. Redis connectivity
    try:
        r.ping()
        print("[OK] Redis connected")
    except redis.ConnectionError:
        print("[FAIL] Redis not reachable")
        sys.exit(1)

    # 2. Check heartbeats
    messages = r.xrevrange("system:heartbeat", count=50)
    agents: dict[str, float] = {}
    now = time.time()

    for msg_id, data in messages:
        raw = data.get(b"_data", b"")
        if raw:
            parsed = json.loads(raw)
            agent_type = parsed.get("agent_type", "?")
            ts = parsed.get("timestamp", "")
            if agent_type not in agents:
                agents[agent_type] = 0

    if agents:
        print(f"[OK] {len(agents)} agent types active:")
        for agent_type in sorted(agents):
            print(f"     - {agent_type}")
    else:
        print("[WARN] No agent heartbeats found")

    # 3. Check stream lengths
    streams = [
        "market:candle:KRW-BTC",
        "market:ticker:KRW-BTC",
        "signal:ta",
        "signal:ml",
        "signal:sentiment",
        "order:request",
        "order:filled",
    ]
    print("\nStream lengths:")
    for stream in streams:
        try:
            length = r.xlen(stream)
            print(f"  {stream}: {length}")
        except Exception:
            print(f"  {stream}: (not found)")


if __name__ == "__main__":
    main()
