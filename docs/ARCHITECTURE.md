# Architecture

## Overview

```
swingtrader/
├── core/           Settings, logging, errors, constants
├── db/             SQLite schema, migrations, backup/restore
├── data/           CSV loader, OHLCV validator, instrument/candle store
├── strategies/     Indicators, signal engine, signal persistence
├── risk/           Position sizing, portfolio risk checks
├── costs/          Indian transaction-cost engine
├── backtest/       Backtest engine, metrics, persistence
├── paper/          Simulated order/position engine
├── market/         yfinance provider, scanner, news, planner, alerts, notify
├── ai/             Rule-based local assistant (disabled by default)
├── broker/         Broker adapter interface (DISABLED — no live orders)
└── web/            Flask app, routes, Jinja2 templates, static assets
```

## Data flow

1. **Import**: CSV → loader (parse, limit) → validator (OHLC, dupes, gaps) → store (SQLite)
2. **Signal**: candles → indicators (causal) → rule evaluation → SignalResult
3. **Size**: signal + portfolio state → risk engine → PositionPlan
4. **Backtest**: chronological loop → signal@close(i) → entry@open(i+1) → exits → metrics
5. **Paper**: order → slippage → costs → cash/position update → ledger
6. **Market**: yfinance → provenance-labeled quotes → scanner/news/alerts → UI

## Key design decisions

- **SQLite** for zero-config local persistence with WAL mode
- **Pydantic** for validated settings (risk limits, cost rates, strategy params)
- **Flask** for lightweight local web server (loopback only, CSRF-protected)
- **Plotly.js** via CDN for interactive charts (no Python plotting overhead)
- **Causal indicators**: every value at index `i` uses only rows `<= i` (no look-ahead)
- **Broker methods raise OrderError**: live trading is structurally impossible in this release
- **yfinance is END_OF_DAY/delayed only**: never labeled as real-time; provenance labels enforce honesty
