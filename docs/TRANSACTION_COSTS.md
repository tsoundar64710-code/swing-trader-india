# Transaction Costs

## Verified rates (checked 2026-10-11)

The default cost rates in `CostAssumptions` were verified against official sources on **2026-10-11**. The `config_verified_date` field is set to `"2026-10-11"`. Every performance report displays the verification date.

**Sources:**
- NSE STT schedule: https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies
- NSE stamp duty: https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes
- SEBI turnover fee: same NSE page (Rs 10 per crore = 0.0001%)
- GST on broker services: 18% (standard rate)

## Unit convention (critical)

Every field ending in `_pct` in `CostAssumptions` is a **PERCENTAGE**. The engine computes:

```
charge = turnover_inr * pct_field / 100
```

so `pct_field = 0.1` means **0.1%** of turnover, `18.0` means **18%**, etc.

## Modelled charges (delivery equity)

| Charge | Buy | Sell | Verified rate | Notes |
|---|---|---|---|---|
| Brokerage | ✓ | ✓ | 0% default (discount broker) | Full-service may charge 0.03% + Rs 20 min |
| STT | ✓ | ✓ | **0.1%** of turnover | Both sides for delivery |
| Exchange txn charge | ✓ | ✓ | **~0.00297%** | NSE schedule |
| SEBI turnover fee | ✓ | ✓ | **0.0001%** | Rs 10 per crore |
| GST | ✓ | ✓ | **18%** on (brokerage + exchange + SEBI) | Not on STT or stamp |
| Stamp duty | ✓ | ✗ | **0.015%** | Buy side only |
| Slippage | ✓ | ✓ | user-configurable (default 0.05%) | **Not a fee** — execution assumption |

## Slippage model

Slippage adjusts the **fill price**, not a separate fee line:

```
buy_fill  = reference_price × (1 + slippage_pct / 100)
sell_fill = reference_price × (1 − slippage_pct / 100)
```

Default: **0.05%** adverse slippage (conservative mid-point for liquid large-caps). Raise for smallcaps or thin order books. Kept separate from statutory fees so users can see the distinction clearly.

## Small-position warning

When round-trip statutory costs exceed 10% of notional (typical only with full-service Rs 20 minimum brokerage on very small orders), the risk engine adds a warning. With 0% delivery brokerage at discount brokers, statutory costs are ~0.22% round trip — small but never zero.

## How to re-verify rates

1. Check your broker's official pricing page
2. Check NSE charges circular
3. Check SEBI turnover fee schedule
4. Update `CostAssumptions` in Settings
5. Set `config_verified_date` to the verification date (or "UNVERIFIED" if guessing)
