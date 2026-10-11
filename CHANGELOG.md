# CHANGELOG

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
- 100 automated tests, ruff lint clean
- Live trading hard-disabled (LIVE_TRADING_ENABLED=False, broker methods raise OrderError)

### Known Limitations
- Cost rates marked UNVERIFIED (placeholder values)
- Single-instrument backtest only (no multi-asset portfolio backtest)
- No sector classification data
- No corporate-actions handling (splits/dividends)
- BSE support is structural only (no verified BSE data source)
- AI assistant not yet implemented (Phase 8)
