# Known Limitations

This is an honest assessment of what the application does and does not do.

## Data limitations

- **No built-in market data feed.** You must supply your own OHLCV CSV files.
- **No verified live quotes.** All prices are historical close/open from imported data.
- **No corporate actions.** Splits, dividends, bonuses, and mergers are not adjusted — your imported data must already be adjusted or you must be aware of this.
- **BSE not verified.** NSE is the primary exchange. BSE mappings are structural only.
- **Stale data possible.** The validator warns but does not block; users must update CSVs manually.
- **No fundamentals.** Earnings, ratios, and news are not available.

## Strategy limitations

- **One strategy implemented** (`trend_pullback_v1`), long-only. It is a research candidate, not a proven edge.
- **No multi-asset portfolio backtest.** Backtests run one instrument at a time.
- **No sector/industry classification.** Diversification checks are by symbol count only.
- **No position sizing across correlated instruments.** Each trade is sized independently.

## Backtesting limitations

- **Simple execution model.** Signals fill at next open with fixed slippage; no order-book simulation.
- **Stop-gap model is conservative but approximate.** Intra-bar path is unknown; stop takes priority over target.
- **Transaction cost rates are UNVERIFIED placeholders.** Verify with official sources before trusting any cost-inclusive result.
- **No walk-forward optimization.** Walk-forward validates fixed parameters; it does not optimize them.
- **No Monte Carlo, regime detection, or survivorship-bias correction.**
- **Zero-trade results are failures, not successes** — reported as such.

## Trading limitations

- **Live trading is disabled and will remain disabled** until a separate, explicitly approved phase.
- **No broker connectivity.** Groww integration is a documented plan only.
- **No automatic market data updates.**
- **Paper trading uses imported historical data only** — it does not stream live prices, so "paper" fills are simulated against the last known historical bars, not a live tape.
- **No mobile app, alerts, email, or notifications.** The app must be open in a browser.

## Infrastructure limitations

- **Single-user, single-machine.** No multi-user, remote access, or collaboration.
- **Local SQLite only.** No cloud sync, no PostgreSQL.
- **No automated test of UI rendering.** Pages are smoke-tested (HTTP 200) only.
- **AI assistant not implemented** (Phase 8).
- **No timezone-aware market calendar.** Indian sessions are handled by data dates, not a live exchange calendar.

## Known risks of use

- Stop-losses do not guarantee exit prices.
- Backtest results do not predict future performance.
- Small-position costs can dominate returns.
- Always verify prices independently before acting on them.
