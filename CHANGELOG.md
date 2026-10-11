# CHANGELOG

## 0.2.1 (2026-10-11) — Security & Cleanup Release

### Added
- CSRF protection on all state-changing endpoints (POST/PUT/DELETE/PATCH).
  Lightweight manual token: random per-install, stored in Flask session,
  validated via `hmac.compare_digest`. No new dependencies.
- Random-per-install session secret key (persisted to `data/.secret_key`,
  gitignored). Replaces hardcoded `"swingtrader-local-only"`.

### Changed
- `data/settings.json` reset to verified defaults: correct STT 0.1%,
  stamp duty 0.015%, exchange 0.00297%, SEBI 0.0001%, `ai.enabled=false`.
  Prior file had stale UNVERIFIED rates that undercharged costs 10-100x.

### Removed
- Dead Streamlit UI (`src/swingtrader/ui/`, 11 files). Unused since Flask
  migration; no external imports.

### Fixed
- Version string bumped to 0.2.1 (was 0.1.0 while changelog said 0.2.0).
- Documentation reconciled: 17 pages, 30+ API endpoints, EOD-only market
  data, notification scope (in-app + Windows toast only, no email/SMS),
  Streamlit removal, CSRF status in SECURITY.md, duplicate rows in
  PROJECT_STATUS.md.

## 0.2.0 (2026-10-11) — Market Intelligence Release

### Added
- yfinance market data provider with explicit provenance labels
  (LIVE/DELAYED/END_OF_DAY/HISTORICAL/UNAVAILABLE — never claims LIVE)
- Market dashboard: NSE/BSE session status, 13 indices, 14 global/macro
  tickers, breadth (advance/decline), sector strength
- Stock scanner with transparent 8-component scoring (trend, momentum,
  volume, structure, volatility, liquidity, relative strength, R:R).
  NO_CLEAR_SETUP verdict when evidence is weak — no forced picks.
- News retrieval via Yahoo Finance with publisher/time/URL, impact
  interpretation tags (separated from facts), freshness and dedupe
- Trade Planner: entry zone, stop, targets, R:R after costs, risk-based
  sizing, max rupee loss, full cost breakdown, invalidation conditions,
  reasons-to-avoid
- Alert engine: stop/target proximity, breakout/breakdown, volume spike,
  big move, stale data. Cooldown dedupe per condition.
- Notification centre: in-app log, Windows desktop toast, quiet hours,
  severity filter, duplicate suppression, delivery-failure recording
- AI assistant upgraded with market context (status, indices, sectors,
  macro, news summary, scanner guidance)
- 29 new tests (total 159)

### Fixed
- Transaction-cost rates corrected 10-100x (STT, stamp duty, exchange,
  SEBI) against official NSE/SEBI sources; verified 2026-10-11
- Backtest engine now enforces max_position_pct
- Slippage doc/code mismatch resolved

### Known Limitations
- yfinance data is END_OF_DAY/delayed — never real-time tick data
- News coverage is sparse on weekends; provider-dependent
- Public holidays not fetched (market_status notes this)
- No email/Telegram notifications (by design, no secrets)

## 0.1.0 (2026-10-11) — Initial Release

### Added
- SQLite schema with migrations, backup/restore
- CSV OHLCV import with validation (dedup, gap detection, staleness, OHLC checks)
- Deterministic indicators: SMA, EMA, Wilder RSI, ATR, rolling support/resistance
- Rule-based trend-pullback strategy with full rule audit trail
- Position sizing with risk limits, whole-share rounding, cost-aware rechecks
- Indian transaction-cost engine (brokerage, STT, GST, stamp duty, SEBI, slippage)
- Backtest engine: signal@close(i), entry@open(i+1), stop-gap model, chronological splits, walk-forward
- Look-ahead / leakage regression tests
- Paper-trading engine: dedupe, reconciliation, restart persistence, stop/target monitoring
- Flask web UI: 9 pages, 16 JSON API endpoints, dark theme, Plotly.js charts
- Portfolio & Risk page with concentration chart and breach detection
- Trade Journal page with rationale, exit, violations, lessons
- Local rule-based assistant (Phase 8): disabled by default, answers factual
  questions about watchlist/signals/positions/cash/journal/strategy/risk/costs
  from the local DB only; refuses buy/sell advice; no external model calls
- 114 automated tests, ruff lint clean
- Live trading hard-disabled (LIVE_TRADING_ENABLED=False, broker methods raise OrderError)

### Known Limitations
- Cost rates marked UNVERIFIED (placeholder values)
- Single-instrument backtest only (no multi-asset portfolio backtest)
- No sector classification data
- No corporate-actions handling (splits/dividends)
- BSE support is structural only (no verified BSE data source)
- AI assistant not yet implemented (Phase 8)
