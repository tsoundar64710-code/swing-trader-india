# Known Limitations

This is an honest assessment of what the application does and does not do.

## Data limitations

- **yfinance market data is END_OF_DAY/delayed — never real-time tick data.** All quotes are labeled with provenance (END_OF_DAY/HISTORICAL); none claim LIVE.
- **CSV import is the primary verified data path.** yfinance is an optional convenience provider.
- **No corporate actions.** Splits, dividends, bonuses, and mergers are not adjusted — your imported data must already be adjusted or you must be aware of this.
- **BSE not verified.** NSE is the primary exchange. BSE mappings are structural only.
- **Stale data possible.** The validator warns but does not block; users must update CSVs manually.
- **No fundamentals.** Earnings and ratios are not available (news is available via Yahoo Finance with impact tagging).

## Strategy limitations

- **One strategy implemented** (`trend_pullback_v1`), long-only. It is a research candidate, not a proven edge.
- **No multi-asset portfolio backtest.** Backtests run one instrument at a time.
- **No sector/industry classification for backtests.** Market-intelligence scanner provides sector strength but is not wired into backtest diversification checks.
- **No position sizing across correlated instruments.** Each trade is sized independently.

## Backtesting limitations

- **Simple execution model.** Signals fill at next open with fixed slippage; no order-book simulation.
- **Stop-gap model is conservative but approximate.** Intra-bar path is unknown; stop takes priority over target.
- **Transaction cost rates are VERIFIED 2026-10-11** against official NSE/SEBI/Stamp sources. Rates can change — re-verify periodically.
- **No walk-forward optimization.** Walk-forward validates fixed parameters; it does not optimize them.
- **No Monte Carlo, regime detection, or survivorship-bias correction.**
- **Zero-trade results are failures, not successes** — reported as such.

## Trading limitations

- **Live trading is disabled and will remain disabled** until a separate, explicitly approved phase.
- **No broker connectivity.** Groww integration is a documented plan only.
- **No automatic market data updates** beyond optional yfinance EOD fetch.
- **Paper trading uses last known bars (imported or yfinance EOD)** — it does not stream live prices, so "paper" fills are simulations, not a live tape.
- **Notifications are local-only**: in-app log + optional Windows desktop toast. No email, SMS, Telegram, or webhook (by design — no secrets stored). App must be open in a browser for toast.

## Infrastructure limitations

- **Single-user, single-machine.** No multi-user, remote access, or collaboration.
- **Local SQLite only.** No cloud sync, no PostgreSQL.
- **No automated test of UI rendering.** Pages are smoke-tested (HTTP 200) only.
- **AI assistant is rule-based only.** It answers factual questions from local DB + market context data and refuses buy/sell advice. It is not a language model and cannot analyze charts.
- **No timezone-aware market calendar.** Indian sessions are handled by data dates and yfinance session status, not a live exchange calendar.

## Known risks of use

- Stop-losses do not guarantee exit prices.
- Backtest results do not predict future performance.
- Small-position costs can dominate returns.
- Always verify prices independently before acting on them.
