"""Market data provider built on yfinance (Yahoo Finance).

PROVENANCE LABELS (never claim more than the source provides):
    LIVE        — real-time tick feed. NOT available via yfinance. Never used.
    DELAYED     — exchange-delayed quote (typically 15 min). NOT guaranteed by yfinance.
    END_OF_DAY  — last completed session close. This is what yfinance daily data is.
    HISTORICAL  — imported CSV or stored candles of past sessions.

yfinance returns daily OHLCV for NSE (.NS) and BSE (.BO) tickers. These are
END-OF-DAY / delayed snapshots from Yahoo Finance — never real-time ticks.
Every quote returned by this module carries an explicit source, timestamp and
quality label so the UI can display it truthfully.

Provider failures return structured errors, never fabricated prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

PROVIDER_NAME = "yahoo_finance"
PROVIDER_URL = "https://finance.yahoo.com"

# Nifty / Sensex / sector ETF proxies available on Yahoo Finance.
# ETF proxies are used because Yahoo does not stream NSE index candles reliably
# for all indices; the proxy is labeled as such.
INDEX_PROXIES: dict[str, dict[str, str]] = {
    "NIFTY_50": {"symbol": "^NSEI", "name": "Nifty 50", "exchange": "NSE"},
    "SENSEX": {"symbol": "^BSESN", "name": "Sensex", "exchange": "BSE"},
    "NIFTY_BANK": {"symbol": "^NSEBANK", "name": "Nifty Bank", "exchange": "NSE"},
    "NIFTY_IT": {"symbol": "^CNXIT", "name": "Nifty IT", "exchange": "NSE"},
    "NIFTY_FMCG": {"symbol": "^CNXFMCG", "name": "Nifty FMCG", "exchange": "NSE"},
    "NIFTY_PHARMA": {"symbol": "^CNXPHARMA", "name": "Nifty Pharma", "exchange": "NSE"},
    "NIFTY_METAL": {"symbol": "^CNXMETAL", "name": "Nifty Metal", "exchange": "NSE"},
    "NIFTY_AUTO": {"symbol": "^CNXAUTO", "name": "Nifty Auto", "exchange": "NSE"},
    "NIFTY_FINANCE": {
        "symbol": "^CNXFINANCE", "name": "Nifty Financial Services", "exchange": "NSE",
    },
    "NIFTY_REALTY": {"symbol": "^CNXREALTY", "name": "Nifty Realty", "exchange": "NSE"},
    "NIFTY_ENERGY": {"symbol": "^CNXENERGY", "name": "Nifty Energy", "exchange": "NSE"},
    "NIFTY_MEDIA": {"symbol": "^CNXMEDIA", "name": "Nifty Media", "exchange": "NSE"},
    "NIFTY_PRIVATE_BANK": {"symbol": "^NSEBANK", "name": "Nifty Bank (proxy)", "exchange": "NSE"},
}

# Global / macro tickers useful for market-impact context.
MACRO_TICKERS: dict[str, dict[str, str]] = {
    "US_SNP500": {"symbol": "^GSPC", "name": "S&P 500", "region": "US"},
    "US_NASDAQ": {"symbol": "^IXIC", "name": "Nasdaq Composite", "region": "US"},
    "US_DOW": {"symbol": "^DJI", "name": "Dow Jones", "region": "US"},
    "ASIA_NIKKEI": {"symbol": "^N225", "name": "Nikkei 225", "region": "Asia"},
    "ASIA_HANGSENG": {"symbol": "^HSI", "name": "Hang Seng", "region": "Asia"},
    "ASIA_SHANGHAI": {"symbol": "000001.SS", "name": "Shanghai Composite", "region": "Asia"},
    "ASIA_KOSPI": {"symbol": "^KS11", "name": "KOSPI", "region": "Asia"},
    "CRUDE_OIL": {"symbol": "CL=F", "name": "WTI Crude", "region": "Commodity"},
    "BRENT_OIL": {"symbol": "BZ=F", "name": "Brent Crude", "region": "Commodity"},
    "GOLD": {"symbol": "GC=F", "name": "Gold Futures", "region": "Commodity"},
    "USD_INR": {"symbol": "USDINR=X", "name": "USD/INR", "region": "Currency"},
    "US_10Y": {"symbol": "^TNX", "name": "US 10Y Yield", "region": "Rates"},
    "INDIA_10Y": {"symbol": "^IN10Y", "name": "India 10Y Yield", "region": "Rates"},
    "VIX": {"symbol": "^INDIAVIX", "name": "India VIX", "region": "Volatility"},
}

# Sector classification for NSE stocks (approximate, GICS-like grouping).
# Used for sector-strength aggregation when a stock's sector is unknown.
SECTOR_MAP: dict[str, str] = {
    "RELIANCE": "Energy", "TCS": "IT", "HDFCBANK": "Financials",
    "ICICIBANK": "Financials", "INFY": "IT", "HINDUNILVR": "FMCG",
    "ITC": "FMCG", "SBIN": "Financials", "BHARTIARTL": "Telecom",
    "KOTAKBANK": "Financials", "LT": "Industrials", "AXISBANK": "Financials",
    "ASIANPAINT": "Consumer", "MARUTI": "Auto", "HCLTECH": "IT",
    "SUNPHARMA": "Pharma", "TITAN": "Consumer", "ULTRACEMCO": "Materials",
    "BAJFINANCE": "Financials", "WIPRO": "IT", "ONGC": "Energy",
    "NTPC": "Utilities", "POWERGRID": "Utilities", "TATAMOTORS": "Auto",
    "TATASTEEL": "Materials", "JSWSTEEL": "Materials", "ADANIENT": "Industrials",
    "ADANIPORTS": "Industrials", "COALINDIA": "Energy", "BAJAJFINSV": "Financials",
    "TECHM": "IT", "HINDALCO": "Materials", "DRREDDY": "Pharma",
    "CIPLA": "Pharma", "EICHERMOT": "Auto", "BRITANNIA": "FMCG",
    "APOLLOHOSP": "Healthcare", "DIVISLAB": "Pharma", "HEROMOTOCO": "Auto",
    "BAJAJ-AUTO": "Auto", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG",
    "SBILIFE": "Financials", "HDFCLIFE": "Financials", "INDUSINDBK": "Financials",
    "GRASIM": "Materials", "LTIM": "IT",
    "BPCL": "Energy", "SHRIRAMFIN": "Financials", "TRENT": "Consumer",
    "BEL": "Industrials", "HAL": "Industrials", "ZOMATO": "Consumer",
    "DMART": "Consumer", "PIDILITIND": "Materials", "SIEMENS": "Industrials",
    "ADANIPOWER": "Utilities", "TATAPOWER": "Utilities", "INDIGO": "Industrials",
}


@dataclass
class Quote:
    """A single price observation with explicit provenance.

    quality must be one of: LIVE, DELAYED, END_OF_DAY, HISTORICAL, UNAVAILABLE.
    This app NEVER reports LIVE for yfinance data.
    """

    symbol: str
    name: str
    price: float | None
    prev_close: float | None = None
    change_abs: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    day_range: str = ""
    timestamp: str = ""  # ISO-8601 of the observation
    quality: str = "UNAVAILABLE"  # LIVE | DELAYED | END_OF_DAY | HISTORICAL | UNAVAILABLE
    source: str = PROVIDER_NAME
    source_url: str = PROVIDER_URL
    currency: str = "INR"
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name, "price": self.price,
            "prev_close": self.prev_close, "change_abs": self.change_abs,
            "change_pct": self.change_pct, "open": self.open, "high": self.high,
            "low": self.low, "volume": self.volume, "day_range": self.day_range,
            "timestamp": self.timestamp, "quality": self.quality,
            "source": self.source, "source_url": self.source_url,
            "currency": self.currency, "error": self.error, "extra": self.extra,
        }


@dataclass
class MarketStatus:
    """Indian market session status (NSE cash: 09:15-15:30 IST, Mon-Fri)."""

    is_open: bool
    session: str  # PRE_OPEN | OPEN | CLOSED | WEEKEND | HOLIDAY_UNKNOWN
    now_ist: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "is_open": self.is_open, "session": self.session,
            "now_ist": self.now_ist, "note": self.note,
        }


def market_status(now_utc: datetime | None = None) -> MarketStatus:
    """Determine NSE cash-market session status from the current UTC time.

    Uses the standard NSE cash session (09:15-15:30 IST, Mon-Fri).
    Public holidays are NOT fetched (no network call here) — the note
    flags this limitation honestly.
    """
    from zoneinfo import ZoneInfo

    now = now_utc or datetime.now(UTC)
    ist = now.astimezone(ZoneInfo("Asia/Kolkata"))
    hhmm = ist.hour * 60 + ist.minute
    weekday = ist.weekday()  # 0=Mon .. 6=Sun
    ts = ist.isoformat()

    if weekday >= 5:
        return MarketStatus(False, "WEEKEND", ts, "Weekend — NSE closed.")
    if hhmm < 9 * 60 + 15:
        return MarketStatus(False, "PRE_OPEN", ts, "Before 09:15 IST — pre-open/closed.")
    if hhmm >= 15 * 60 + 30:
        return MarketStatus(False, "CLOSED", ts, "After 15:30 IST — cash session closed.")
    return MarketStatus(
        True, "OPEN", ts,
        "NSE cash session open (09:15-15:30 IST). Public holidays not checked.",
    )


def to_nse(symbol: str) -> str:
    """Normalise a bare symbol to Yahoo NSE suffix (.NS) if not already suffixed."""
    s = symbol.strip().upper()
    if s.endswith((".NS", ".BO", ".IN")) or s.startswith("^"):
        return s
    return f"{s}.NS"


def fetch_quote(symbol: str, *, period: str = "5d", auto_adjust: bool = True) -> Quote:
    """Fetch a daily quote for an NSE/BSE symbol via yfinance.

    Returns END_OF_DAY quality (never LIVE). On provider failure the Quote
    carries quality=UNAVAILABLE and a populated `error` — never a fake price.
    """
    import yfinance as yf

    yahoo_sym = to_nse(symbol)
    now = datetime.now(UTC).isoformat()
    try:
        t = yf.Ticker(yahoo_sym)
        # fast_info gives last close + prev close without downloading full history
        fi = t.fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        prev = fi.get("previousClose") or fi.get("prev_close")
        if price is None:
            # fallback: last close from daily history
            hist = t.history(period=period, auto_adjust=auto_adjust)
            if hist is None or len(hist) == 0:
                return Quote(
                    symbol=symbol, name=yahoo_sym, price=None,
                    quality="UNAVAILABLE", timestamp=now,
                    error=f"No data returned for {yahoo_sym}.",
                )
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
            open_ = float(hist["Open"].iloc[-1])
            high = float(hist["High"].iloc[-1])
            low = float(hist["Low"].iloc[-1])
            vol = int(hist["Volume"].iloc[-1])
        else:
            price = float(price)
            prev = float(prev) if prev is not None else None
            open_ = fi.get("open") or fi.get("dayOpen")
            high = fi.get("dayHigh") or fi.get("high")
            low = fi.get("dayLow") or fi.get("low")
            vol = fi.get("lastVolume") or fi.get("volume")

        change = (price - prev) if (price is not None and prev) else None
        change_pct = (100 * change / prev) if (change is not None and prev) else None
        dr = f"{low:.2f} – {high:.2f}" if (low and high) else ""
        return Quote(
            symbol=symbol.upper(), name=yahoo_sym, price=round(price, 2),
            prev_close=round(prev, 2) if prev else None,
            change_abs=round(change, 2) if change is not None else None,
            change_pct=round(change_pct, 2) if change_pct is not None else None,
            open=round(open_, 2) if open_ else None,
            high=round(high, 2) if high else None,
            low=round(low, 2) if low else None,
            volume=int(vol) if vol else None,
            day_range=dr, timestamp=now,
            quality="END_OF_DAY",
            error=None,
        )
    except Exception as exc:  # yfinance raises many exception types
        log.warning("fetch_quote failed for %s: %s", yahoo_sym, exc)
        return Quote(
            symbol=symbol.upper(), name=yahoo_sym, price=None,
            quality="UNAVAILABLE", timestamp=now,
            error=f"Provider unavailable for {yahoo_sym}: {exc}",
        )


def fetch_history(
    symbol: str, *, period: str = "6mo", interval: str = "1d", auto_adjust: bool = True
) -> tuple[list[dict], str | None]:
    """Fetch daily OHLCV history as a list of row dicts.

    Returns (rows, error). rows carry quality=HISTORICAL.
    On failure rows is empty and error explains why — never fabricates data.
    """
    import yfinance as yf

    yahoo_sym = to_nse(symbol)
    try:
        t = yf.Ticker(yahoo_sym)
        hist = t.history(period=period, interval=interval, auto_adjust=auto_adjust)
        if hist is None or len(hist) == 0:
            return [], f"No history returned for {yahoo_sym}."
        rows = []
        for idx, row in hist.iterrows():
            rows.append({
                "ts": str(idx)[:19],
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
                "quality": "HISTORICAL",
                "source": PROVIDER_NAME,
            })
        return rows, None
    except Exception as exc:
        log.warning("fetch_history failed for %s: %s", yahoo_sym, exc)
        return [], f"History unavailable for {yahoo_sym}: {exc}"


def fetch_quotes(symbols: list[str]) -> list[Quote]:
    """Batch-fetch quotes. Each symbol is independent — one failure does not
    block the rest."""
    return [fetch_quote(s) for s in symbols]


def fetch_indices(keys: list[str] | None = None) -> list[Quote]:
    """Fetch index/ETF-proxy quotes. Returns END_OF_DAY quality quotes."""
    keys = keys or list(INDEX_PROXIES.keys())
    out: list[Quote] = []
    for k in keys:
        meta = INDEX_PROXIES.get(k)
        if not meta:
            continue
        q = fetch_quote(meta["symbol"])
        q.name = meta["name"]
        q.extra["index_key"] = k
        q.extra["exchange"] = meta["exchange"]
        q.extra["is_index_proxy"] = True
        out.append(q)
    return out


def fetch_macro(keys: list[str] | None = None) -> list[Quote]:
    """Fetch global/macro tickers (US markets, commodities, currencies, yields)."""
    keys = keys or list(MACRO_TICKERS.keys())
    out: list[Quote] = []
    for k in keys:
        meta = MACRO_TICKERS.get(k)
        if not meta:
            continue
        q = fetch_quote(meta["symbol"])
        q.name = meta["name"]
        q.extra["macro_key"] = k
        q.extra["region"] = meta["region"]
        q.currency = "USD" if meta["region"] in ("US", "Commodity", "Currency", "Rates") else "INR"
        out.append(q)
    return out


def market_breadth(quotes: list[Quote]) -> dict:
    """Compute advance/decline breadth from a list of stock quotes."""
    advances = declines = unchanged = errors = 0
    for q in quotes:
        if q.price is None or q.change_pct is None:
            errors += 1
        elif q.change_pct > 0:
            advances += 1
        elif q.change_pct < 0:
            declines += 1
        else:
            unchanged += 1
    total = advances + declines + unchanged
    ad_ratio = round(advances / declines, 2) if declines else (float(advances) if advances else 1.0)
    return {
        "advances": advances, "declines": declines, "unchanged": unchanged,
        "unavailable": errors, "total": total, "ad_ratio": ad_ratio,
        "breadth": "BULLISH" if advances > declines * 1.5 else (
            "BEARISH" if declines > advances * 1.5 else "NEUTRAL"
        ),
    }


def sector_strength(quotes: list[Quote], sector_of: dict[str, str] | None = None) -> dict:
    """Aggregate average change_pct by sector. `sector_of` maps SYMBOL -> sector."""
    sector_of = sector_of or SECTOR_MAP
    buckets: dict[str, list[float]] = {}
    for q in quotes:
        if q.change_pct is None:
            continue
        sec = sector_of.get(q.symbol.upper(), "Other")
        buckets.setdefault(sec, []).append(q.change_pct)
    out = {}
    for sec, vals in buckets.items():
        out[sec] = {
            "avg_change_pct": round(sum(vals) / len(vals), 2),
            "count": len(vals),
            "strongest": max(vals),
            "weakest": min(vals),
        }
    ranked = sorted(out.items(), key=lambda kv: kv[1]["avg_change_pct"], reverse=True)
    return {
        "sectors": out,
        "ranking": [s for s, _ in ranked],
        "strongest_sector": ranked[0][0] if ranked else None,
        "weakest_sector": ranked[-1][0] if ranked else None,
    }
