# Risk Management

## Risk limits (configurable in Settings)

| Limit | Default | Description |
|---|---|---|
| Max capital committed | 50% | Total capital that can be deployed |
| Max position % | 20% | Largest single-position allocation |
| Max portfolio exposure % | 50% | Total invested as % of equity |
| Max risk per trade % | 1% | Maximum loss from entry to stop |
| Max open positions | 3 | Simultaneous holdings |
| Max drawdown % | 15% | Equity peak-to-trough limit |
| Daily loss limit % | 3% | Session loss before blocking new trades |
| Loss cooldown | 2 sessions | Pause after reaching loss threshold |

## Position sizing

For a long position:

```
risk_per_share = entry_reference − stop_price
risk_budget = equity × max_risk_per_trade_pct / 100
qty_by_risk = floor(risk_budget / (risk_per_share + per_share_round_trip_cost))
qty_by_cash = floor(cash / (entry + per_share_buy_cost))
qty = min(qty_by_risk, qty_by_cash, qty_by_notional_limit)
```

After fees are applied, the plan is re-checked against every limit. If any check fails, the trade is rejected with a clear reason.

## Emergency stop

- Global `trading_disabled` flag blocks all position sizing
- Every broker method raises `OrderError` (live trading impossible)

## Stop-loss limitations

A stop-loss does **not** guarantee its exit price. Gaps can cause fills far below the stop. The backtest engine models this (`stop_gap` exit reason). Always assume losses can exceed the planned amount.
