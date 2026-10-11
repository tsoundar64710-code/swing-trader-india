# Market Data

## Supported sources

- **User-supplied CSV files** (primary, Phase 2)
- Official broker APIs (future, requires verification)
- Licensed providers (future)

## CSV format

Required columns (case-insensitive):
```
Date, Open, High, Low, Close, Volume
```

Accepted date column aliases: `Date`, `Timestamp`, `Datetime`, `Time`
Accepted volume aliases: `Volume`, `Vol`, `V`

## Validation pipeline

1. Parse and type-check all numeric columns
2. Drop rows with invalid timestamps, NaN values, non-positive prices
3. Drop rows failing OHLC relationships (high ≥ open/close/low, low ≤ open/close/high)
4. Remove duplicate timestamps (keep latest)
5. Sort chronologically
6. Detect missing weekday sessions (warning only — never fabricates candles)
7. Check staleness (configurable threshold, default 7 days)

## Data provenance recorded

- Instrument symbol and exchange
- Interval and timezone
- Data provider name and source type
- Import timestamp
- Adjusted/unadjusted status
- Row count, date range, validation status
- Warnings (gaps, staleness, dropped rows)

## Important distinctions

| Concept | Meaning |
|---|---|
| Latest historical close | Last imported candle's close price |
| Verified live quote | NOT available in this release |
| Simulated execution price | Historical price + slippage assumption |
| Actual broker fill | NOT available (live trading disabled) |

## Limitations

- No automatic corporate-action adjustment (splits/dividends)
- No BSE data source verified yet
- User must supply their own historical data
- No real-time or delayed quotes
