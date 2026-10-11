# Strategies

## trend_pullback_v1

Long-only swing setup based on trend following with momentum confirmation.

### Rules (evaluated in order)

| # | Rule | Type | Description |
|---|---|---|---|
| R1 | Close > slow SMA | Core | Long-term uptrend |
| R2 | Fast SMA > slow SMA | Core | Trend structure |
| R3 | Pullback to fast SMA | Core | Recent low touched fast-SMA zone (3 bars) |
| R4 | RSI < overbought | Core | Momentum not exhausted |
| R5 | Volume ≥ volume SMA | Advisory | Volume confirmation |
| R6 | Close > invalidation | Core | Above structural stop |
| R7 | R:R ≥ minimum | Core | Reward-to-risk acceptable |

### Actions

- **BUY_SETUP**: All core rules (R1-R4, R6, R7) satisfied
- **WAIT**: Some trend rules pass but not all core rules
- **NO_TRADE**: Insufficient data, stale data, or core rules fail
- **SELL_EXIT_SETUP**: Reserved for future sell-side signals

### Entry / Exit

- **Entry reference**: Latest close
- **Stop**: Close − (ATR × multiplier)
- **Target**: Entry + (min_R:R × risk_per_share)
- **Invalidation**: Slow SMA

### Important

This is a **research candidate**, not a proven strategy. Backtest results do not predict future performance. Parameters are configurable in Settings and Strategy Lab.

## Indicators

| Indicator | Method | Notes |
|---|---|---|
| SMA | Rolling mean | min_periods = window |
| EMA | Exponential (span) | adjust=False |
| RSI | Wilder smoothing | ewm alpha=1/period |
| ATR | True Range + Wilder | Uses high/low/close |
| Rolling low/high | 20-bar support/resistance | Context only |
