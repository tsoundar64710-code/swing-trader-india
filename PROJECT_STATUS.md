# PROJECT_STATUS.md

Living status report. Statuses: NOT STARTED / IN PROGRESS / IMPLEMENTED / TESTED / VERIFIED.
"VERIFIED" requires executed automated tests or a documented manual check with evidence.

Last updated: 2026-10-11 (Phase 2 complete)

## Overall

| Area | Status | Evidence |
|---|---|---|
| Implementation completion (weighted) | **~24%** | See checklist below |
| Automated tests | **TESTED — 48/48 passed** | `python -m pytest` → `48 passed in 3.74s` (2026-10-11) |
| Lint (ruff) | **VERIFIED — clean** | `python -m ruff check src tests` → `All checks passed!` |
| Data-provider verification | NOT STARTED | CSV provider in Phase 2 |
| Security review | IN PROGRESS | Phase 1 basics done (no secrets, redacted logs, loopback bind, broker blocked); full review in Phase 9 |
| Backtesting verification | NOT STARTED | Phase 5 |
| Paper-trading verification | NOT STARTED | Phase 6 |
| **Live trading** | **DISABLED (by design)** | `LIVE_TRADING_ENABLED=False`; broker methods raise `OrderError`; test `test_no_live_orders.py` |

## Feature checklist (weighted)

| # | Feature | Weight | Status | Notes |
|---|---|---|---|---|
| 1 | Repo/env, deps, settings validation | 5 | VERIFIED | tests/test_settings.py (7 tests) |
| 2 | SQLite schema + migrations + backup/restore | 8 | VERIFIED | tests/test_database.py (8 tests) |
| 3 | Logging with redaction | 3 | VERIFIED | tests/test_logging.py (4 tests) |
| 4 | Broker interface (blocked live orders) | 3 | VERIFIED | tests/test_no_live_orders.py (9 tests) |
| 5 | App shell (Streamlit, loopback) | 3 | IMPLEMENTED | Manual boot check 2026-10-11 on 127.0.0.1:8599 |
| 6 | CSV market-data import + validation | 10 | VERIFIED | tests/test_market_data.py (22 tests) |
| 7 | Data Centre + watchlist UI | 5 | IMPLEMENTED | Pages wired; imports verified via store tests; manual UI pass pending |
| 8 | Indicators + strategies + Signal Centre | 12 | NOT STARTED | Phase 3 |
| 9 | Stock research page | 5 | NOT STARTED | Phase 3 |
| 10 | Risk engine + position sizing | 8 | NOT STARTED | Phase 4 |
| 11 | Transaction-cost engine | 6 | NOT STARTED | Phase 4 |
| 12 | Backtest engine + leakage tests | 14 | NOT STARTED | Phase 5 |
| 13 | Paper trading + reconciliation | 12 | NOT STARTED | Phase 6 |
| 14 | Portfolio/risk + journal | 7 | NOT STARTED | Phase 7 |
| 15 | Optional AI assistant (disabled default) | 2 | NOT STARTED | Phase 8 |
| 16 | Security hardening + release evidence | 5 | NOT STARTED | Phase 9 |
| 17 | Documentation set | 5 | IN PROGRESS | README + status now; full docs by Phase 9 |

## Environment (verified)

- Python 3.14.7 (venv at `.venv`)
- Dependencies pinned in requirements.txt (installed 2026-10-11)
- OS: Windows 11, 8 GB RAM target

## Decisions & assumptions

- Project created from scratch; working directory had no prior trading code.
- Default paper capital ₹10,000 (user may change in Settings; ₹1,000/month contributions tracked manually).
- Cost rates in `CostAssumptions` are unverified placeholders flagged `config_verified_date="UNVERIFIED"` until checked against official sources.
- Python 3.14 used (verified compatible with pinned deps) instead of 3.12.

## Next action

Phase 3: deterministic indicators + transparent strategy + Signal Centre + Stock Research page, including a look-ahead/leakage regression test.
