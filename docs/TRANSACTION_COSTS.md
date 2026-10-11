# Transaction Costs

## Important: rates are UNVERIFIED

The default cost rates in `CostAssumptions` are **placeholders**. The `config_verified_date` field is set to `"UNVERIFIED"`. Every performance report displays a warning until you verify current rates with official sources (NSE, broker, SEBI).

## Modelled charges (delivery equity)

| Charge | Buy | Sell | Notes |
|---|---|---|---|
| Brokerage | ✓ | ✓ | max(turnover × rate, minimum) |
| STT | ✓ | ✓ | Stamp duty on buy; STT differs by side |
| Exchange transaction charge | ✓ | ✓ | NSE rate |
| SEBI turnover fee | ✓ | ✓ | ₹10 per crore equivalent |
| GST | ✓ | ✓ | 18% on (brokerage + exchange + SEBI) |
| Stamp duty | ✓ | ✗ | Buy-side only |
| Slippage | ✓ | ✓ | Price impact, not a fee |

## Slippage model

```
buy_fill = reference_price × (1 + slippage_pct / 100)
sell_fill = reference_price × (1 − slippage_pct / 100)
```

Default: 0.5% adverse slippage.

## Small-position warning

When round-trip costs exceed 10% of notional (typical for very small positions), the risk engine adds a warning. With ₹1,000/month contributions, transaction costs can dominate returns — the system will reject trades that cannot justify the costs.

## How to verify rates

1. Check your broker's official pricing page
2. Check NSE charges circular
3. Check SEBI turnover fee schedule
4. Update `CostAssumptions` in Settings
5. Set `config_verified_date` to the verification date
