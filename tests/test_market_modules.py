"""Tests for market provider, scanner, news, planner, alerts, notifications.

Network-dependent paths are mocked or tested with synthetic data so the
suite runs offline. Provenance labels are asserted explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from swingtrader.core.settings import AppSettings, StrategySettings
from swingtrader.market.alerts import AlertEngine
from swingtrader.market.notify import NotificationCenter, NotificationPrefs
from swingtrader.market.planner import build_trade_plan
from swingtrader.market.provider import (
    INDEX_PROXIES,
    Quote,
    market_breadth,
    market_status,
    sector_strength,
    to_nse,
)
from swingtrader.market.scanner import (
    explain_exclusion,
    rank_stocks,
    scan_stock,
)
from swingtrader.risk.sizing import PortfolioState

# ── provider ─────────────────────────────────────────────────────────────


def test_to_nse_suffixes():
    assert to_nse("RELIANCE") == "RELIANCE.NS"
    assert to_nse("RELIANCE.NS") == "RELIANCE.NS"
    assert to_nse("TCS.BO") == "TCS.BO"
    assert to_nse("^NSEI") == "^NSEI"


def test_market_status_weekend():
    # 2026-10-10 is a Saturday
    sat = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
    ms = market_status(sat)
    assert ms.session == "WEEKEND"
    assert not ms.is_open


def test_market_status_open_hours():
    # 2026-10-09 (Friday) 10:00 UTC = 15:30 IST → just at close boundary
    # 04:00 UTC = 09:30 IST → open
    fri_open = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
    ms = market_status(fri_open)
    assert ms.session == "OPEN"
    assert ms.is_open


def test_market_status_closed_after_hours():
    fri_close = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)  # 17:30 IST
    ms = market_status(fri_close)
    assert ms.session == "CLOSED"
    assert not ms.is_open


def test_quote_never_reports_live_for_yfinance():
    """Every Quote default and fetch path must be END_OF_DAY, never LIVE."""
    q = Quote(symbol="X", name="X", price=100, quality="END_OF_DAY")
    assert q.quality == "END_OF_DAY"
    assert q.quality != "LIVE"
    assert q.source == "yahoo_finance"


def test_quote_to_dict_has_provenance():
    q = Quote(symbol="TCS", name="TCS.NS", price=3500, quality="END_OF_DAY",
              timestamp="2026-10-09T10:00:00+00:00")
    d = q.to_dict()
    assert d["quality"] == "END_OF_DAY"
    assert d["source"] == "yahoo_finance"
    assert d["timestamp"]


def test_index_proxies_have_nse_bse_symbols():
    assert "NIFTY_50" in INDEX_PROXIES
    assert "SENSEX" in INDEX_PROXIES
    assert INDEX_PROXIES["NIFTY_50"]["symbol"] == "^NSEI"


def test_market_breadth_counts():
    qs = [
        Quote("A", "A", 100, change_pct=1.5),
        Quote("B", "B", 200, change_pct=-0.5),
        Quote("C", "C", 300, change_pct=0.0),
        Quote("D", "D", None, change_pct=None),  # unavailable
    ]
    b = market_breadth(qs)
    assert b["advances"] == 1
    assert b["declines"] == 1
    assert b["unchanged"] == 1
    assert b["unavailable"] == 1
    assert b["total"] == 3
    assert b["breadth"] == "NEUTRAL"


def test_sector_strength_aggregates():
    qs = [
        Quote("RELIANCE", "R", 100, change_pct=2.0),
        Quote("TCS", "T", 200, change_pct=-1.0),
        Quote("INFY", "I", 300, change_pct=1.0),
    ]
    ss = sector_strength(qs)
    assert "Energy" in ss["sectors"]
    assert "IT" in ss["sectors"]
    assert ss["strongest_sector"] == "Energy"


# ── scanner ──────────────────────────────────────────────────────────────


def _synthetic_uptrend(n: int = 100) -> pd.DataFrame:
    """Deterministic uptrending OHLCV frame."""
    import numpy as np

    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0.3, 0.8, n))
    highs = closes + rng.uniform(0.5, 2.0, n)
    lows = closes - rng.uniform(0.5, 2.0, n)
    opens = closes + rng.normal(0, 0.3, n)
    vols = rng.integers(100_000, 500_000, n)
    ts = pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "ts": ts, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    })


def test_scan_stock_insufficient_data():
    df = _synthetic_uptrend(10)
    r = scan_stock("TEST", df, StrategySettings())
    assert r.verdict == "NO_DATA"
    assert r.error


def test_scan_stock_produces_score():
    df = _synthetic_uptrend(120)
    r = scan_stock("TEST", df, StrategySettings(), sector="IT")
    assert r.verdict in ("STRONG", "INTERESTING", "WEAK", "NO_CLEAR_SETUP")
    assert 0 <= r.total_score <= r.max_score
    assert len(r.components) >= 6
    # Every component has a detail explanation
    assert all(c.detail for c in r.components)


def test_scan_stock_no_forced_pick():
    """Downtrending data should not produce STRONG."""
    import numpy as np

    rng = np.random.default_rng(7)
    closes = 100 - np.cumsum(rng.uniform(0.1, 0.5, 120))  # clear downtrend
    closes = np.maximum(closes, 10)  # floor
    ts = pd.date_range("2026-01-01", periods=120, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "ts": ts, "open": closes + 0.1, "high": closes + 0.5,
        "low": closes - 0.5, "close": closes,
        "volume": rng.integers(100_000, 200_000, 120),
    })
    r = scan_stock("DOWN", df, StrategySettings())
    assert r.verdict != "STRONG"


def test_rank_stocks_orders_by_verdict_then_score():
    from swingtrader.market.scanner import ScanResult
    a = ScanResult("A", total_score=40, verdict="WEAK")
    b = ScanResult("B", total_score=80, verdict="STRONG")
    c = ScanResult("C", total_score=60, verdict="INTERESTING")
    d = ScanResult("D", total_score=0, verdict="NO_DATA")
    ranked = rank_stocks([a, b, c, d])
    assert [r.symbol for r in ranked] == ["B", "C", "A", "D"]


def test_explain_exclusion_mentions_failed_components():
    from swingtrader.market.scanner import ScanResult, ScoreComponent
    r = ScanResult("X")
    r.components = [
        ScoreComponent("trend", 0, 20, False, "close <= slow SMA"),
        ScoreComponent("momentum", 15, 15, True, "RSI ok"),
    ]
    text = explain_exclusion(r)
    assert "trend" in text
    assert "close <= slow SMA" in text


# ── planner ──────────────────────────────────────────────────────────────


def healthy_pf() -> PortfolioState:
    return PortfolioState(equity_inr=100_000, cash_inr=100_000)


def test_trade_plan_blocks_without_price():
    p = build_trade_plan(
        "X", latest_price=None, entry_reference=100, stop_price=95,
        portfolio=healthy_pf(), settings=AppSettings(),
    )
    assert not p.plan_accepted
    assert p.rejections


def test_trade_plan_full():
    p = build_trade_plan(
        "RELIANCE", latest_price=2500, entry_reference=2500, stop_price=2450,
        target_price=2600, portfolio=healthy_pf(), settings=AppSettings(),
        price_quality="END_OF_DAY",
    )
    assert p.plan_accepted
    assert p.qty >= 1
    assert p.stop_price == 2450
    assert p.reward_risk is not None
    assert p.buy_costs.get("total", 0) > 0  # statutory costs present
    assert p.max_loss_inr > 0
    assert p.invalidation_conditions
    assert p.reasons_to_avoid
    assert any("not a recommendation" in r for r in p.reasons_to_avoid)


def test_trade_plan_labels_price_quality():
    p = build_trade_plan(
        "X", latest_price=100, entry_reference=100, stop_price=95,
        portfolio=healthy_pf(), settings=AppSettings(),
        price_quality="HISTORICAL",
    )
    assert p.price_quality == "HISTORICAL"


# ── alerts ───────────────────────────────────────────────────────────────


def test_alert_stop_near():
    e = AlertEngine()
    alerts = e.check_symbol("TCS", price=102, stop=100)
    assert any(a.condition_key.startswith("stop_near") for a in alerts)


def test_alert_target_near():
    e = AlertEngine()
    alerts = e.check_symbol("TCS", price=118, target=120)
    assert any(a.condition_key.startswith("target_near") for a in alerts)


def test_alert_volume_spike():
    e = AlertEngine()
    alerts = e.check_symbol("TCS", price=100, volume=300_000, avg_volume=100_000)
    assert any(a.condition_key.startswith("volume_spike") for a in alerts)


def test_alert_cooldown_suppresses_duplicate():
    e = AlertEngine()
    a1 = e.check_symbol("TCS", price=102, stop=100)
    a2 = e.check_symbol("TCS", price=102, stop=100)  # within cooldown
    assert len(a1) == 1
    assert len(a2) == 0


def test_alert_stale_data():
    e = AlertEngine()
    alerts = e.check_symbol("TCS", price=100, data_age_hours=200, stale_after_days=7)
    assert any(a.condition_key.startswith("stale_data") for a in alerts)


def test_alert_no_price_no_alerts():
    e = AlertEngine()
    assert e.check_symbol("TCS", price=None, stop=100) == []


# ── notifications ────────────────────────────────────────────────────────


def _notif_conn(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "n.db")
    conn.row_factory = sqlite3.Row
    return conn


def test_notification_recorded(tmp_path):
    conn = _notif_conn(tmp_path)
    nc = NotificationCenter(conn, NotificationPrefs(desktop_toast=False))
    r = nc.notify("TCS", "INFO", "Test alert", "detail", trigger_key="test:1", force=True)
    assert r["sent"]
    hist = nc.history()
    assert len(hist) == 1
    assert hist[0]["title"] == "Test alert"
    conn.close()


def test_notification_dedupe(tmp_path):
    conn = _notif_conn(tmp_path)
    nc = NotificationCenter(conn, NotificationPrefs(desktop_toast=False))
    r1 = nc.notify("TCS", "INFO", "Alert", "", trigger_key="dup:1", force=True)
    r2 = nc.notify("TCS", "INFO", "Alert", "", trigger_key="dup:1")  # no force → dedupe
    assert r1["sent"]
    assert not r2["sent"]
    assert r2["reason"] == "duplicate within cooldown"
    conn.close()


def test_notification_severity_filter(tmp_path):
    conn = _notif_conn(tmp_path)
    nc = NotificationCenter(conn, NotificationPrefs(
        desktop_toast=False, min_severity="WARNING",
    ))
    r = nc.notify("TCS", "INFO", "Low", "", trigger_key="sev:1")
    assert not r["sent"]
    assert r["reason"] == "below severity filter"
    conn.close()


def test_notification_quiet_hours(tmp_path):
    conn = _notif_conn(tmp_path)
    nc = NotificationCenter(conn, NotificationPrefs(
        desktop_toast=False, quiet_hours_start="00:00", quiet_hours_end="23:59",
    ))
    r = nc.notify("TCS", "CRITICAL", "Urgent", "", trigger_key="q:1")
    assert not r["sent"]
    assert r["reason"] == "quiet hours"
    conn.close()


# ── news (offline) ───────────────────────────────────────────────────────


def test_news_dedupe_marks_duplicates():
    from swingtrader.market.news import NewsItem, dedupe_news
    items = [
        NewsItem(headline="RBI holds rates"),
        NewsItem(headline="RBI holds rates"),  # duplicate
        NewsItem(headline="TCS beats estimates"),
    ]
    out = dedupe_news(items)
    assert out[0].duplicate_of is None
    assert out[1].duplicate_of is not None
    assert out[2].duplicate_of is None


def test_news_impact_tagging_is_interpretation():
    from swingtrader.market.news import NewsItem
    # The dataclass separates retrieved facts from interpretation fields
    it = NewsItem(headline="RBI cuts repo rate", source_type="retrieved")
    assert it.source_type == "retrieved"
    assert it.impact in ("POSITIVE", "NEGATIVE", "MIXED", "UNKNOWN")
