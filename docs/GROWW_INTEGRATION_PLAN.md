# Groww Integration Plan

## Status: NOT IMPLEMENTED — requires separate approval

Live trading is **hard-disabled** in this release. The broker adapter interface exists but every method raises `OrderError`.

## Pre-requisites before any live-trading phase

### 1. Verify Groww API access
- Check official Groww API documentation (groww.in/trade-api)
- Confirm account eligibility for API access
- Verify pricing (free tier vs paid)
- Understand rate limits and permissions
- Review terms of service

### 2. Compliance review
- SEBI regulations for retail algorithmic trading
- Exchange rules (NSE/BSE) for API-based orders
- Broker's own algo-trading policy
- Tax implications (STT, capital gains)
- Consider professional advice if unsure

### 3. Technical requirements (separate implementation)
- OAuth2 or API-key authentication
- Token storage (encrypted, never in Git or DB plaintext)
- Order preview with manual confirmation (symbol, side, qty, price, costs)
- Duplicate-submission prevention (idempotency keys)
- Order-status reconciliation
- Partial-fill handling
- Network timeout handling (NO blind retries)
- Rate-limit compliance
- Market-session validation (9:15-15:30 IST)
- Audit logging of every order event
- Kill switch / emergency stop
- Explicit live-mode activation (not a config toggle)

### 4. Testing requirements
- Full paper-trading soak test (minimum 30 days)
- Order simulation against historical data
- Edge-case testing (gaps, halts, circuit breakers)
- Reconciliation accuracy verification

## What this plan does NOT authorize

- Automatic order submission without human confirmation
- Bypassing broker or exchange controls
- Use of unverified or unofficial APIs
