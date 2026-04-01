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

## Safety

- 종목당 최대 포지션: 총자산의 30%
- 일일 최대 손실: 10만원
- 단일 주문 최대: 5만원
- 드로다운 보호: 고점 대비 5% 하락 시 전량 청산
- Graceful shutdown: 미체결 주문 자동 취소
