# Local Assistant

## Overview

The assistant (Phase 8) answers factual questions about your own local trading data. It is **disabled by default** and must be explicitly enabled on the Assistant page.

## What it is

- Rule-based question answering over the local SQLite database
- No external LLM, no API keys, no network calls
- Reports facts: watchlist, signals, positions, cash, journal, strategy params, risk limits, transaction costs

## What it is NOT

- Not an investment advisor — refuses buy/sell/recommendation questions
- Not a language model — cannot analyze charts, news, or unseen text
- Not connected to any external data source

## Enabled behavior

1. Go to `/assistant` and click "Enable assistant"
2. Ask questions in plain English (e.g., "What is my cash?", "Show my signals", "What are my risk limits?")
3. The assistant replies with data from your database only
4. Questions containing advice-seeking phrasing ("should I buy...", "recommend...") are refused

## Disabling

Click "Disable" on the Assistant page. The API returns HTTP 403 when disabled.

## Privacy

All processing is local. No question text, portfolio data, or settings leave your machine.
