"""Streamlit entry point.

Run: streamlit run src/swingtrader/ui/app.py --server.address 127.0.0.1
Binds to loopback only — never expose this app to the public internet.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without installing the package (lightweight local use).
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

from swingtrader import APP_NAME, LIVE_TRADING_ENABLED, OPERATING_MODE, __version__
from swingtrader.core.logging_setup import setup_logging
from swingtrader.core.settings import DATA_DIR, DB_PATH, load_settings
from swingtrader.db.database import init_database

st.set_page_config(
    page_title=APP_NAME,
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

setup_logging(DATA_DIR / "logs")
settings = load_settings()
conn = init_database(DB_PATH)


def _sidebar() -> None:
    st.sidebar.title("📈 Swing Trader India")
    st.sidebar.caption(f"v{__version__}")
    st.sidebar.markdown(f"**Mode:** `{OPERATING_MODE}`")
    if not LIVE_TRADING_ENABLED:
        st.sidebar.success("Live trading: DISABLED (research & paper only)")
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Educational research tool. Not investment advice. "
        "Past performance never guarantees future results."
    )


def page_dashboard() -> None:
    st.title("Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Operating mode", "Research / Paper")
    col2.metric("Initial capital (simulated)", f"₹{settings.initial_capital_inr:,.0f}")
    col3.metric("Open positions", "0")
    st.info(
        "Market data, signals, backtesting and paper trading arrive in later phases. "
        "See PROJECT_STATUS.md for verified progress."
    )
    st.markdown(
        f"""
| Item | Status |
|---|---|
| App version | {__version__} |
| Database | `{DB_PATH.name}` (migrated) |
| Data directory | `{DATA_DIR}` |
| Live order submission | Not implemented (by design) |
"""
    )


def page_data_centre() -> None:
    from swingtrader.ui.pages.data_centre import render

    render(conn, settings)


def page_watchlist() -> None:
    from swingtrader.ui.pages.watchlist import render

    render(conn, settings)


def page_signal_centre() -> None:
    from swingtrader.ui.pages.signal_centre import render

    render(conn, settings)


def page_stock_research() -> None:
    from swingtrader.ui.pages.stock_research import render

    render(conn, settings)


def page_strategy_lab() -> None:
    from swingtrader.ui.pages.strategy_lab import render

    render(conn, settings)


def page_settings() -> None:
    st.title("Settings")
    st.caption("Changes are validated and saved to data/settings.json.")
    capital = st.number_input(
        "Simulated initial capital (₹)",
        min_value=1000.0,
        value=settings.initial_capital_inr,
        step=1000.0,
    )
    max_pos = st.slider(
        "Max allocation per position (%)", 1.0, 100.0, settings.risk.max_position_pct
    )
    max_open = st.number_input(
        "Max simultaneous positions", 1, 50, settings.risk.max_open_positions
    )
    if st.button("Save settings"):
        settings.initial_capital_inr = float(capital)
        settings.risk.max_position_pct = float(max_pos)
        settings.risk.max_open_positions = int(max_open)
        from swingtrader.core.settings import save_settings

        save_settings(settings)
        st.success("Settings saved.")
    with st.expander("Current effective settings (JSON)"):
        st.code(settings.model_dump_json(indent=2), language="json")
    st.warning(
        "Live trading is hard-disabled in this release and cannot be enabled from Settings."
    )


_sidebar()
_page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Market Watchlist", "Stock Research", "Signal Centre",
     "Strategy Lab", "Data Centre", "Settings"],
    label_visibility="collapsed",
)
if _page == "Data Centre":
    page_data_centre()
elif _page == "Market Watchlist":
    page_watchlist()
elif _page == "Stock Research":
    page_stock_research()
elif _page == "Signal Centre":
    page_signal_centre()
elif _page == "Strategy Lab":
    page_strategy_lab()
elif _page == "Settings":
    page_settings()
else:
    page_dashboard()
