"""Signal Centre: research outputs for every watchlist symbol with data."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import streamlit as st

from swingtrader.core.settings import AppSettings
from swingtrader.data.store import list_watchlist, load_candles
from swingtrader.strategies.signals import trend_pullback_signal


def _is_stale(last_ts: str, settings: AppSettings) -> bool:
    try:
        age = (datetime.now() - datetime.fromisoformat(last_ts)).days
        return age > settings.data.stale_after_days
    except ValueError:
        return True


def compute_for_watchlist(conn: sqlite3.Connection, settings: AppSettings) -> list[dict]:
    out = []
    for row in list_watchlist(conn):
        df = load_candles(conn, row["id"])
        if len(df) == 0:
            out.append(
                {
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "action": "NO_TRADE",
                    "reason": "No data imported",
                    "data_ts": "—",
                    "entry": None,
                    "stop": None,
                    "target": None,
                    "R:R": None,
                    "result": None,
                }
            )
            continue
        stale = _is_stale(str(df["ts"].iloc[-1]), settings)
        sig = trend_pullback_signal(row["symbol"], df, settings.strategy, stale=stale)
        from swingtrader.strategies.persistence import save_signal

        save_signal(conn, row["id"], sig)
        out.append(
            {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "action": sig.action,
                "reason": "; ".join(sig.reasons[:2]),
                "data_ts": sig.data_ts,
                "entry": sig.entry_reference,
                "stop": sig.stop_price,
                "target": sig.target_price,
                "R:R": sig.reward_risk,
                "result": sig,
            }
        )
    return out


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Signal Centre")
    st.caption(
        "Deterministic, rule-based research outputs — not buy/sell instructions. "
        "Every result shows why it fired or why it was rejected."
    )
    st.warning(
        "BUY SETUP = all research rules passed on the latest valid candle. "
        "It does NOT mean the trade will profit. A stop-loss cannot guarantee "
        "its fill price, and losses can exceed the planned amount in a gap."
    )
    results = compute_for_watchlist(conn, settings)
    if not results:
        st.info("Watchlist is empty. Add symbols first.")
        return
    counts: dict[str, int] = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    c = st.columns(len(counts) or 1)
    for col, (k, v) in zip(c, sorted(counts.items()), strict=False):
        col.metric(k, v)

    action_filter = st.multiselect(
        "Filter", ["BUY_SETUP", "WAIT", "SELL_EXIT_SETUP", "NO_TRADE"],
        default=["BUY_SETUP", "WAIT", "SELL_EXIT_SETUP", "NO_TRADE"],
    )
    table = [
        {k: v for k, v in r.items() if k != "result"}
        for r in results
        if r["action"] in action_filter
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)

    with st.expander("Why was a signal rejected?"):
        pick = st.selectbox(
            "Symbol", [r["symbol"] for r in results if r["action"] != "BUY_SETUP"] or ["(none)"]
        )
        match = next((r for r in results if r["symbol"] == pick), None)
        if match and match["result"]:
            sig = match["result"]
            st.markdown(f"**{sig.symbol} → {sig.action}**")
            for reason in sig.reasons:
                st.write("-", reason)
            if sig.rules_failed:
                st.caption("Rules not satisfied: " + ", ".join(sig.rules_failed))
            if sig.rules_satisfied:
                st.caption("Rules satisfied: " + ", ".join(sig.rules_satisfied))
