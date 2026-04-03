# Coin Trader

Upbit KRW 마켓 대상 멀티 에이전트 자동매매 시스템.

## Architecture

8개의 독립 에이전트가 Redis Streams를 통해 통신하며 복합 전략으로 매매를 수행합니다.

```
DataCollector ──> StrategyTA ──┐
              ──> StrategyML ──┤──> PortfolioManager ──> RiskManager ──> Executor
              ──> Sentiment ───┘        ↑                                   │
                                        └──── order:filled/failed ──────────┘
```

## Setup

```bash
# 의존성 설치
uv sync

# 환경변수 설정
cp .env.example .env
# .env 파일에 Upbit API 키 입력

# Redis 실행 (Docker)
docker run -d --name redis -p 6379:6379 redis:latest
```

## Usage

```bash
# 모든 에이전트 실행
uv run coin-trader run all

# 개별 에이전트 실행
uv run coin-trader run data_collector
uv run coin-trader run strategy_ta

# 시스템 상태 확인
uv run coin-trader status
```

## Agents

| Agent | Role |
|-------|------|
| DataCollector | WebSocket/REST로 시장 데이터 수집 |
| StrategyTA | RSI, MACD, BB 등 기술적 분석 |
| StrategyML | GradientBoosting 기반 가격 예측 |
| StrategySentiment | 호가/거래량 기반 시장 심리 분석 |
| PortfolioManager | 복합 시그널 결합 + 매매 결정 |
| RiskManager | 포지션/손실 한도 검증 |
| Executor | Upbit API 주문 실행 |
| Monitor | 시스템 상태 대시보드 |

## Trading Mode & Safety Controls

### Dry-Run / Live Switch

The system defaults to **DRY_RUN** mode — all signals, risk checks, and order
decisions run normally, but the executor **logs orders instead of placing them**
on the exchange.

```bash
# Default (safe) — no real orders
TRADING_MODE=dry_run

# Enable live trading (requires explicit opt-in)
TRADING_MODE=live
```

### Kill Switch

Set `TRADING_ENABLED=false` to immediately halt **all** order flow.  The risk
manager rejects every incoming order while the flag is off.

```bash
TRADING_ENABLED=false   # halt all orders
TRADING_ENABLED=true    # resume (default)
```

### Notifications (Telegram)

Real-time notifications for trading events can be sent to a Telegram chat.

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and get the token.
2. Get your chat ID (message [@userinfobot](https://t.me/userinfobot)).
3. Set env vars and enable in `config/settings.toml`:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=987654321
```

```toml
# config/settings.toml
[notification]
enabled = true
```

**Supported events:**
| Event | When |
|-------|------|
| `buy_signal` | Buy order requested |
| `sell_signal` | Sell order requested |
| `take_profit` | Position closed at profit target |
| `stop_loss` | Position closed at loss limit |
| `order_failure` | Order rejected or failed after retries |
| `system_start` | Executor agent started |
| `critical_error` | Agent crashed unexpectedly |

### Risk Limits

- 종목당 최대 포지션: 총자산의 30%
- 일일 최대 손실: 10만원
- 단일 주문 최대: 5만원
- 드로다운 보호: 고점 대비 5% 하락 시 전량 청산
- Graceful shutdown: 미체결 주문 자동 취소

### Checklist Before Live Trading

1. Run the system in `dry_run` mode first and verify signals/decisions in logs.
2. Set Upbit API keys with **only the permissions you need** (trade-only, no withdrawals).
3. Configure Telegram notifications so you can monitor remotely.
4. Review risk limits in `config/settings.toml`.
5. Only then set `TRADING_MODE=live`.
