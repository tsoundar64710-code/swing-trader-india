"""News retrieval and impact tagging.

Uses yfinance's news endpoint (free, no API key) as the primary source, plus
optional RSS feeds. Retrieved articles are treated as UNTRUSTED CONTENT —
they are displayed as data, never executed as instructions.

Every item carries: headline, publisher, publish time, URL, and a
fact-versus-interpretation separation. Impact tags are model-generated
interpretations, clearly labelled, and never claim causal price impact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

SOURCE_NAME = "yahoo_finance_news"

# Keyword → (sectors, impact) map for India-relevant macro / sector tagging.
# Impact is an INTERPRETATION heuristic, not a factual claim.
MACRO_TAGS: dict[str, tuple[list[str], str]] = {
    "rbi": (["Financials", "Banking"], "MIXED"),
    "repo rate": (["Financials", "Banking", "Real Estate"], "MIXED"),
    "inflation": (["FMCG", "Financials"], "NEGATIVE"),
    "crude": (["Energy", "Paints", "Aviation"], "MIXED"),
    "fed": (["Financials", "IT"], "MIXED"),
    "us markets": (["All"], "MIXED"),
    "war": (["All"], "NEGATIVE"),
    "geopolitical": (["All"], "NEGATIVE"),
    "gdp": (["All"], "MIXED"),
    "budget": (["All"], "MIXED"),
    "GST": (["All"], "MIXED"),
    "earnings": ([], "MIXED"),
    "results": ([], "MIXED"),
    "order win": ([], "POSITIVE"),
    "buyback": ([], "POSITIVE"),
    "dividend": ([], "POSITIVE"),
    "acquisition": ([], "MIXED"),
    "downgrade": ([], "NEGATIVE"),
    "upgrade": ([], "POSITIVE"),
    "guidance": ([], "MIXED"),
    "regulatory": ([], "NEGATIVE"),
    "sebi": (["Financials"], "MIXED"),
}


@dataclass
class NewsItem:
    headline: str
    publisher: str = ""
    published_utc: str = ""
    url: str = ""
    summary: str = ""
    symbols: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    impact: str = "UNKNOWN"  # POSITIVE | NEGATIVE | MIXED | UNKNOWN
    horizon: str = "unknown"  # intraday | days | weeks | unknown
    confidence: str = "low"  # low | medium | high
    is_fresh: bool = True
    age_hours: float | None = None
    duplicate_of: str | None = None
    source: str = SOURCE_NAME
    source_type: str = "retrieved"  # retrieved (fact) | interpreted (model)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "headline": self.headline, "publisher": self.publisher,
            "published_utc": self.published_utc, "url": self.url,
            "summary": self.summary, "symbols": self.symbols,
            "sectors": self.sectors, "impact": self.impact,
            "horizon": self.horizon, "confidence": self.confidence,
            "is_fresh": self.is_fresh, "age_hours": self.age_hours,
            "duplicate_of": self.duplicate_of,
            "source": self.source, "source_type": self.source_type,
            "error": self.error,
        }


def _parse_published(ts_any: Any) -> tuple[str, float | None]:
    """Convert yfinance published timestamp to ISO-8601 UTC + age in hours."""
    now = datetime.now(UTC)
    try:
        if isinstance(ts_any, (int, float)):
            dt = datetime.fromtimestamp(ts_any, tz=UTC)
        elif isinstance(ts_any, str):
            dt = datetime.fromisoformat(ts_any.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        else:
            return "", None
        age_h = (now - dt).total_seconds() / 3600
        return dt.isoformat(), round(age_h, 1)
    except (ValueError, OSError, OverflowError):
        return "", None


def _tag_impact(headline: str, summary: str) -> tuple[list[str], str, str]:
    """Heuristic sector/impact tagging from headline+summary keywords.

    This is an INTERPRETATION, clearly separated from the retrieved fact.
    It never claims the news caused a price move.
    """
    text = f"{headline} {summary}".lower()
    sectors: set[str] = set()
    impacts: list[str] = []
    for kw, (secs, imp) in MACRO_TAGS.items():
        if kw.lower() in text:
            sectors.update(secs)
            impacts.append(imp)
    if not impacts:
        return [], "UNKNOWN", "low"
    # majority vote
    pos = impacts.count("POSITIVE")
    neg = impacts.count("NEGATIVE")
    if pos > neg:
        impact = "POSITIVE"
    elif neg > pos:
        impact = "NEGATIVE"
    else:
        impact = "MIXED"
    conf = "medium" if len(impacts) >= 2 else "low"
    return list(sectors), impact, conf


def fetch_yahoo_news(symbol: str | None = None, *, count: int = 20) -> list[NewsItem]:
    """Fetch news via yfinance. If symbol is given, ticker-specific news;
    otherwise Yahoo Finance trending/headline news.

    Returns NewsItems with source_type='retrieved'. Impact tags are added
    as source_type='interpretation' overlays in the same object.
    """
    import yfinance as yf

    try:
        if symbol:
            t = yf.Ticker(symbol if "." in symbol else f"{symbol}.NS")
            raw_items = t.news or []
        else:
            raw_items = yf.news or []
    except Exception as exc:
        log.warning("fetch_yahoo_news failed: %s", exc)
        return [NewsItem(headline="", error=f"News provider unavailable: {exc}")]

    out: list[NewsItem] = []
    for raw in raw_items[:count]:
        try:
            # yfinance 0.2+/1.x news structure
            content = raw.get("content", raw)
            title = content.get("title") or content.get("headline") or ""
            if not title:
                continue
            publisher = ""
            if isinstance(content.get("provider"), dict):
                publisher = content["provider"].get("displayName", "")
            elif isinstance(content.get("publisher"), str):
                publisher = content["publisher"]
            elif raw.get("publisher"):
                publisher = raw.get("publisher", "")

            url = ""
            if isinstance(content.get("canonicalUrl"), dict):
                url = content["canonicalUrl"].get("url", "")
            elif isinstance(content.get("link"), str):
                url = content["link"]
            elif raw.get("link"):
                url = raw.get("link", "")

            pub_ts = content.get("pubDate") or content.get("providerPublishTime")
            ts_str, age_h = _parse_published(pub_ts)

            summary = ""
            if isinstance(content.get("summary"), str):
                summary = content["summary"]
            elif isinstance(content.get("description"), str):
                summary = content["description"]

            sectors, impact, conf = _tag_impact(title, summary)
            is_fresh = age_h is not None and age_h < 24

            out.append(NewsItem(
                headline=title, publisher=publisher, published_utc=ts_str,
                url=url, summary=summary[:500],
                symbols=[symbol.upper()] if symbol else [],
                sectors=sectors, impact=impact,
                horizon="days" if is_fresh else "unknown",
                confidence=conf, is_fresh=is_fresh, age_hours=age_h,
                source_type="retrieved",
                raw={"_tags_source": "interpretation"},
            ))
        except Exception as exc:
            log.debug("skipping malformed news item: %s", exc)
            continue
    return out


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    """Mark duplicates by headline similarity; keep the first occurrence."""
    seen: set[str] = set()
    for it in items:
        key = it.headline.lower().strip()[:80]
        if key in seen:
            it.duplicate_of = "earlier item with same headline"
        else:
            seen.add(key)
    return items


def filter_fresh(items: list[NewsItem], max_age_hours: float = 72) -> list[NewsItem]:
    return [
        it for it in items
        if it.age_hours is None or it.age_hours <= max_age_hours
    ]


def summarize_news(items: list[NewsItem], max_items: int = 10) -> str:
    """Produce a factual summary of retrieved news for the assistant/UI.

    Distinguishes retrieved facts from interpretation. Never invents items.
    """
    items = [i for i in items if i.headline]
    if not items:
        return "No news items retrieved from the provider."
    fresh = [i for i in items if i.is_fresh]
    lines = [
        f"Retrieved {len(items)} news items ({len(fresh)} fresh <24h). "
        f"Source: {SOURCE_NAME}. Facts below are as published; impact tags are interpretations."
    ]
    for it in items[:max_items]:
        age = f"{it.age_hours:.0f}h ago" if it.age_hours is not None else "time unknown"
        imp = f" [{it.impact}]" if it.impact != "UNKNOWN" else ""
        lines.append(f"- {it.headline} ({it.publisher or 'unknown'}, {age}){imp}")
    return "\n".join(lines)
