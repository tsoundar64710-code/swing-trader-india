"""Market Watchlist page."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from swingtrader.core.errors import DataValidationError
from swingtrader.core.settings import DATA_DIR, AppSettings
from swingtrader.data.store import (
    add_to_watchlist,
    export_watchlist_csv,
    find_instrument,
    get_or_create_instrument,
    list_watchlist,
    remove_from_watchlist,
)


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Market Watchlist")
    st.caption("Symbols you research. Data must be imported in the Data Centre first.")

    with st.form("add_symbol", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        symbol = c1.text_input("Symbol", max_chars=30).strip().upper()
        exchange = c2.selectbox("Exchange", ["NSE", "BSE"], label_visibility="collapsed")
        submitted = c3.form_submit_button("Add", type="primary")
    if submitted and symbol:
        try:
            inst = find_instrument(conn, symbol, exchange)
            if inst is None:
                st.warning(
                    f"{symbol} has no imported data yet. Added with a missing-data "
                    "warning — import a CSV in the Data Centre to enable research."
                )
                iid = get_or_create_instrument(conn, symbol, exchange)
            else:
                iid = inst["id"]
            add_to_watchlist(conn, iid)
        except DataValidationError as exc:
            st.error(str(exc))

    rows = list_watchlist(conn)
    if not rows:
        st.info("Watchlist is empty. Add a symbol above.")
        return

    now = datetime.now(UTC)
    table = []
    for r in rows:
        last_ts = r["last_candle_ts"]
        status = "NO DATA"
        if last_ts:
            try:
                age = (now.replace(tzinfo=None) - datetime.fromisoformat(last_ts)).days
                status = f"{age}d old" if age > settings.data.stale_after_days else "FRESH"
            except ValueError:
                status = "UNKNOWN"
        table.append(
            {
                "symbol": r["symbol"],
                "exchange": r["exchange"],
                "name": r["name"] or "",
                "candles": r["candle_count"],
                "last data": last_ts or "—",
                "data status": status,
            }
        )
    st.dataframe(table, use_container_width=True, hide_index=True)

    stale = [t for t in table if t["data status"] != "FRESH"]
    if stale:
        st.warning(
            f"{len(stale)} symbol(s) have stale or missing data. "
            "Signals from them will be blocked or marked unreliable."
        )

    c1, c2 = st.columns(2)
    with c1:
        to_remove = st.selectbox(
            "Remove symbol", [f"{r['symbol']} ({r['exchange']})" for r in rows]
        )
        if st.button("Remove selected"):
            sym, _, exch = to_remove.partition(" (")
            inst = find_instrument(conn, sym, exch.rstrip(")"))
            if inst:
                remove_from_watchlist(conn, inst["id"])
                st.rerun()
    with c2:
        if st.button("Export watchlist CSV"):
            out = DATA_DIR / "exports" / "watchlist.csv"
            n = export_watchlist_csv(conn, out)
            st.success(f"Exported {n} row(s) to {out}")
            st.download_button(
                "Download watchlist.csv",
                data=out.read_bytes(),
                file_name="watchlist.csv",
                mime="text/csv",
            )
    st.caption(f"Data directory: {Path(DATA_DIR)}")
