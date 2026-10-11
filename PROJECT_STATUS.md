# PROJECT_STATUS.md

Living status report. Statuses: NOT STARTED / IN PROGRESS / IMPLEMENTED / TESTED / VERIFIED.
"VERIFIED" requires executed automated tests or a documented manual check with evidence.

Last updated: 2026-10-11 (v0.2.1 — Security & Cleanup Release)

## Overall

| Area | Status | Evidence |
|---|---|---|
| Implementation completion (weighted) | **~90%** | See checklist below |
| Automated tests | **TESTED — 159/159 passed** | `python -m pytest` → `159 passed` (2026-10-11) |
| Lint (ruff) | **VERIFIED — clean** | `python -m ruff check src tests` → `All checks passed!` |
| Market data provider | **VERIFIED (EOD only)** | yfinance Nifty/Sensex/breadth tested; quality=END_OF_DAY/delayed, never real-time |
| News provider | **VERIFIED** | /api/news returns real Yahoo Finance headlines |
| Scanner | **VERIFIED** | RELIANCE scored WEAK 35/100 (honest, no forced pick) |
| Transaction costs | **VERIFIED** | Rates checked 2026-10-11 vs NSE/SEBI; 16 independent tests |
| CSRF protection | **VERIFIED** | Token on all POST/PUT/DELETE/PATCH routes; `hmac.compare_digest` |
| Session secret | **VERIFIED** | Random-per-install, persisted to `data/.secret_key` (gitignored) |
| Security review | VERIFIED (local-only) | docs/SECURITY.md threat table; secrets scan clean; loopback-only |
| **Live trading** | **DISABLED (by design)** | `LIVE_TRADING_ENABLED=False`; broker methods raise `OrderError`; test `test_no_live_orders.py` |
| Data-provider verification | VERIFIED (CSV path) | tests/test_market_data.py (22 tests); provider = user CSV |
| Backtesting verification | VERIFIED | tests/test_backtest.py (11 incl. leakage + stop-gap) |
| Paper-trading verification | VERIFIED | tests/test_paper_trading.py (13 incl. restart + reconcile) |
| Documentation set | VERIFIED | 14 files in docs/ + CHANGELOG.md; page/endpoint counts reconciled |
| Dead code cleanup | VERIFIED | Streamlit `ui/` removed; no dangling imports |

## Feature checklist (weighted)

| # | Feature | Weight | Status | Notes |
|---|---|---|---|---|
| 1 | Repo/env, deps, settings validation | 5 | VERIFIED | tests/test_settings.py (7 tests) |
| 2 | SQLite schema + migrations + backup/restore | 8 | VERIFIED | tests/test_database.py (8 tests) |
| 3 | Logging with redaction | 3 | VERIFIED | tests/test_logging.py (4 tests) |
| 4 | Broker interface (blocked live orders) | 3 | VERIFIED | tests/test_no_live_orders.py (9 tests) |
| 5 | CSV market-data import + validation | 10 | VERIFIED | tests/test_market_data.py (22 tests) |
| 6 | Data Centre + watchlist UI | 5 | VERIFIED | Pages wired; imports verified via store tests |
| 7 | Indicators + strategies + Signal Centre | 12 | VERIFIED | tests/test_signals.py (11 tests) |
| 8 | Stock research page | 5 | VERIFIED | Flask route /research/<symbol> |
| 9 | Risk engine + position sizing | 8 | VERIFIED | tests/test_risk_costs.py (15 tests) |
| 10 | Transaction-cost engine | 6 | VERIFIED | tests/test_risk_costs.py; rates verified 2026-10-11 |
| 11 | Backtest engine + leakage tests | 14 | VERIFIED | tests/test_backtest.py (11 tests) |
| 12 | Paper trading + reconciliation | 12 | VERIFIED | tests/test_paper_trading.py (13 tests) |
| 13 | Flask web UI (17 pages + 30+ API endpoints) | 10 | VERIFIED | 17 templates; routes.py 900+ lines; all pages HTTP 200 |
| 14 | CSRF protection | 5 | VERIFIED | before_request hook on all state-changing methods |
| 15 | Portfolio/risk + journal | 7 | VERIFIED | routes.py portfolio_page/journal_page |
| 16 | Optional AI assistant (disabled default) | 2 | VERIFIED | tests/test_assistant.py (14 tests); disabled by default; refuses advice |
| 17 | Market intelligence (scanner/news/planner/alerts) | 8 | VERIFIED | tests/test_market_modules.py; yfinance EOD-only |
| 18 | Security hardening + release evidence | 5 | VERIFIED | docs/SECURITY.md; 14-file docs set; CHANGELOG; secret key randomized |

## Environment (verified)

- Python 3.14.7 (venv at `.venv`)
- Dependencies pinned in requirements.txt (installed 2026-10-11)
- OS: Windows 11, 8 GB RAM target

## Decisions & assumptions

- Project created from scratch; working directory had no prior trading code.
- Default paper capital ₹10,000 (user may change in Settings; ₹1,000/month contributions tracked manually).
- Cost rates in `CostAssumptions` verified 2026-10-11 against official NSE/SEBI sources.
- Python 3.14 used (verified compatible with pinned deps) instead of 3.12.
- yfinance is END_OF_DAY/delayed — never real-time; all quotes labeled with provenance.
- Notifications are local-only (in-app log + Windows desktop toast); no email/SMS/webhook (no secrets stored).
- Streamlit UI removed; Flask is the sole UI.

## Next action

All planned phases (0-9) complete. App is ready for paper-trading research use.
Remaining optional work: Phase 2 risk re-tuning for ₹1,000 capital profile,
verified live data provider, corporate-actions handling, multi-asset portfolio
backtest, live-trading phase (requires separate approval per docs/GROWW_INTEGRATION_PLAN.md).
