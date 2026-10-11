"""Data Centre page: CSV import, validation report, import history."""

from __future__ import annotations

import sqlite3

import streamlit as st

from swingtrader.core.errors import DataValidationError
from swingtrader.core.settings import AppSettings
from swingtrader.data.loader import load_ohlcv_csv
from swingtrader.data.store import (
    get_or_create_instrument,
    list_imports,
    save_import,
)
from swingtrader.data.validator import validate_ohlcv


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Data Centre")
    st.caption(
        "Import daily OHLCV history from CSV files you supply. "
        "Prices are never invented — invalid rows are dropped and reported."
    )

    tab_import, tab_history = st.tabs(["Import", "Import history"])

    with tab_import:
        st.markdown(
            """
**Expected CSV format** (column names, case-insensitive):
`Date, Open, High, Low, Close, Volume`
— `Timestamp`/`Datetime` accepted for the date column. Daily bars recommended for swing research.
"""
        )
        uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
        col1, col2, col3 = st.columns(3)
        symbol = col1.text_input("Symbol (e.g. RELIANCE)", max_chars=30).strip().upper()
        exchange = col2.selectbox("Exchange", ["NSE", "BSE"])
        adjusted = col3.selectbox(
            "Adjusted data?", ["unknown", "adjusted", "unadjusted"],
            help="Splits/dividends handling. Unknown adds an extra warning to reports.",
        )
        if st.button("Validate and import", type="primary", disabled=not uploaded):
            try:
                raw = uploaded.getvalue()
                report_df = load_ohlcv_csv(
                    raw,
                    max_mb=settings.data.max_import_file_mb,
                    max_rows=settings.data.max_import_rows,
                )
                clean, rep = validate_ohlcv(
                    report_df,
                    stale_after_days=settings.data.stale_after_days,
                )
                st.subheader("Validation report")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Rows read", f"{rep.total_rows:,}")
                m2.metric("Rows kept", f"{rep.valid_rows:,}")
                m3.metric("Duplicates removed", rep.duplicates_removed)
                m4.metric("Invalid OHLC rows", rep.dropped_invalid_ohlc)
                for w in rep.warnings:
                    st.warning(w)
                for e in rep.errors:
                    st.error(e)
                if not rep.ok or len(clean) == 0:
                    st.error("Import blocked: dataset failed validation.")
                    return
                iid = get_or_create_instrument(conn, symbol, exchange)
                save_import(
                    conn, iid, clean, rep,
                    timezone_name=settings.data.timezone,
                    source_name=uploaded.name or "upload.csv",
                    source_type="csv",
                    adjusted=adjusted,
                )
                st.success(
                    f"Imported {rep.valid_rows:,} candles for {symbol} "
                    f"({rep.date_start} → {rep.date_end})."
                )
            except DataValidationError as exc:
                st.error(str(exc))

    with tab_history:
        imports = list_imports(conn)
        if not imports:
            st.info("No imports yet.")
        else:
            st.dataframe(
                [
                    {
                        "symbol": r["symbol"],
                        "exchange": r["exchange"],
                        "rows": r["row_count"],
                        "from": r["date_start"],
                        "to": r["date_end"],
                        "adjusted": r["adjusted"],
                        "status": r["validation_status"],
                        "imported_at": r["imported_at"][:19],
                        "source": r.get("source_name") or "csv",
                    }
                    for r in imports
                ],
                use_container_width=True,
            )
