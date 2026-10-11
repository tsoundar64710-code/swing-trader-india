# Backtesting

## Timing model

1. Signal evaluated on **close of bar i** using only data ≤ i
2. Entry executes at **open of bar i+1** with adverse slippage
3. Stop executes at stop price, or at next open if bar gaps through (worse fill)
4. Target executes at target price if touched
5. Stop takes priority over target when both hit in same bar (conservative)

## Splits

- **Full sample**: All data, single run
- **Chronological splits**: 60% train / 20% validation / 20% test (non-overlapping)
- **Walk-forward**: Anchored expanding window, fixed parameters (no re-optimization)

## Metrics

| Metric | Definition |
|---|---|
| Net return % | (final_equity − initial) / initial × 100 |
| Net P&L | Sum of trade P&L (net of costs) |
| Benchmark return | Buy & hold from first open to last close |
| Excess return | Net return − benchmark return |
| Win rate % | Winning trades / total trades × 100 |
| Profit factor | Gross profit / gross loss |
| Max drawdown % | Largest peak-to-trough equity decline |
| Avg holding | Average bars in position per trade |
| Total costs | Sum of brokerage + taxes + fees across all trades |

## No-look-ahead protections

- Indicators use only past rows (causal rolling windows)
- Signals computed on prefix windows only
- Regression test: appending future bars must not change earlier indicator values
- Regression test: trades fully inside a prefix must match the full run

## Warnings shown to user

- Zero-trade runs are NOT reported as successful
- Cost rates are UNVERIFIED placeholders
- Past performance never guarantees future returns
- Overfitting, survivorship bias, and regime change apply
