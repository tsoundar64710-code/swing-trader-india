# AI Swing-Trading Research Assistant — India

A lightweight, local-first research and paper-trading platform for Indian
NSE/BSE cash-equity swing trading. Built for a single retail user on a Windows
laptop with 8 GB RAM. **No live order submission. No guaranteed returns.**

## What it does

| Feature | Status |
|---|---|
| CSV historical data import + validation | ✅ Tested (22 tests) |
| Market watchlist with freshness warnings | ✅ Implemented |
| Deterministic indicators (SMA, RSI, ATR, volume) | ✅ Tested (11 tests) |
| Rule-based signal engine (BUY_SETUP / WAIT / NO_TRADE) | ✅ Tested |
| Position sizing + risk limits + cost engine | ✅ Tested (15 tests) |
| Backtesting with leakage protections | ✅ Tested (11 tests) |
| Paper-trading engine with reconciliation | ✅ Tested (13 tests) |
| Flask web UI (9 pages, 16 API endpoints) | ✅ HTTP 200 tested |
| Portfolio & Risk page | ✅ Implemented |
| Trade Journal page | ✅ Implemented |
| Optional local AI assistant | ✅ Implemented (disabled by default, local rules only) |
| Live trading (Groww) | ❌ Disabled by design |

## Quick start (Windows)

```powershell
# One-time setup
cd swing-trader-india
.\scripts\setup.ps1

# Run the app (opens http://127.0.0.1:8501)
.\scripts\run.ps1
# or double-click: scripts\start_app.bat

# Run tests
.\scripts\test.ps1

# Backup database
.\scripts\backup.ps1
```

## Requirements

- Python 3.12+ (tested on 3.14)
- Windows 10/11
- ~200 MB disk for dependencies
- No GPU, no Docker, no cloud services
- Flask + Plotly.js (CDN) for the web UI

## Data

Import daily OHLCV CSV files with columns:
`Date, Open, High, Low, Close, Volume`

Invalid rows are dropped and reported. Missing candles are never fabricated.

## Safety

- Live trading is **hard-disabled** in code (`LIVE_TRADING_ENABLED = False`)
- All broker methods raise `OrderError`
- Binds to `127.0.0.1` only (never expose to the internet)
- No API keys required or stored
- Cost rates are marked UNVERIFIED until checked against official sources

## Disclaimer

This is an educational research tool, not investment advice. Past performance
never guarantees future results. You are responsible for all trading decisions.

## License

Private / personal use.
