# Testing

## Running tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Test categories

| File | Tests | Covers |
|---|---|---|
| test_settings.py | 7 | Settings validation, save/load, live-trading flag |
| test_database.py | 8 | Migrations, transactions, backup/restore, constraints |
| test_logging.py | 4 | Secret redaction, handler idempotency |
| test_no_live_orders.py | 9 | All broker methods blocked |
| test_market_data.py | 22 | CSV import, OHLCV validation, store, export |
| test_signals.py | 11 | Indicators, signal rules, no-lookahead |
| test_signal_persistence.py | 1 | Signal audit trail |
| test_risk_costs.py | 15 | Cost engine, position sizing, risk limits |
| test_backtest.py | 11 | Backtest engine, splits, leakage, gap model |
| test_backtest_persistence.py | 1 | Backtest run storage |
| test_paper_trading.py | 13 | Orders, fills, cash, dedupe, restart, reconciliation |

**Total: 100 tests**

## Synthetic data

All test fixtures use deterministic synthetic price paths (numpy seeded random walks). They do NOT represent real securities and make no claims about market accuracy.

## Key regression tests

- **No-lookahead**: Appending future bars must not change earlier indicator values
- **Prefix consistency**: Trades fully inside a data prefix must match the full run
- **Stop-gap**: A bar opening below the stop must fill at the open (worse price)
- **Broker blocked**: Every broker method must raise OrderError
- **Reconciliation**: Ledger sum must match last balance after any trade sequence
