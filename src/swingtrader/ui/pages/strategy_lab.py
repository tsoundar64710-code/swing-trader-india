"""Strategy Lab: configure, backtest, compare splits."""

from __future__ import annotations

import copy
import sqlite3

import plotly.graph_objects as go
import streamlit as st

from swingtrader.backtest.engine import run_backtest, run_split_backtest, run_walk_forward
from swingtrader.backtest.persistence import save_backtest_run
from swingtrader.core.settings import AppSettings
from swingtrader.costs.engine import cost_warning
from swingtrader.data.store import find_instrument, list_watchlist, load_candles


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Strategy Lab")
    st.caption(
        "Historical simulation on imported data. Backtests NEVER predict future returns. "
        "Results below are labelled by data split and carry their assumptions."
    )
    st.warning(cost_warning(settings.costs))

    rows = list_watchlist(conn)
    symbols_with_data = [r for r in rows if r["candle_count"] > 0]
    if not symbols_with_data:
        st.info("Import data for at least one watchlist symbol first.")
        return

    pick = st.selectbox("Symbol", [f"{r['symbol']} ({r['exchange']})" for r in symbols_with_data])
    sym, _, exch = pick.partition(" (")
    inst = find_instrument(conn, sym, exch.rstrip(")"))
    df = load_candles(conn, inst["id"])

    with st.expander("Strategy parameters (trend_pullback_v1)"):
        p = copy.deepcopy(settings.strategy)
        c1, c2, c3 = st.columns(3)
        p.sma_fast = c1.number_input("Fast SMA", 2, 200, p.sma_fast)
        p.sma_slow = c2.number_input("Slow SMA", 5, 400, p.sma_slow)
        p.rsi_period = c3.number_input("RSI period", 2, 50, p.rsi_period)
        c4, c5, c6 = st.columns(3)
        p.atr_period = c4.number_input("ATR period", 2, 50, p.atr_period)
        p.atr_stop_multiplier = c5.number_input("ATR stop ×", 0.5, 6.0, p.atr_stop_multiplier, 0.1)
        p.min_reward_risk = c6.number_input("Min reward:risk", 0.5, 10.0, p.min_reward_risk, 0.1)
        if p.sma_slow <= p.sma_fast:
            st.error("Slow SMA must be greater than fast SMA.")
            return

    mode = st.radio(
        "Mode", ["Full sample", "Chronological splits", "Walk-forward"], horizontal=True
    )
    capital = st.number_input("Initial capital (₹)", 1_000.0, 10_000_000.0,
                              settings.initial_capital_inr, 1_000.0)
    s = copy.deepcopy(settings)
    s.strategy = p

    if st.button("Run backtest", type="primary"):
        with st.spinner("Running…"):
            if mode == "Full sample":
                results = {"full": run_backtest(df, s, initial_capital=capital, symbol=sym)}
            elif mode == "Chronological splits":
                results = run_split_backtest(df, s, initial_capital=capital)
                for r in results.values():
                    r.config["symbol"] = sym
            else:
                results = {"walk_forward": run_walk_forward(df, s, initial_capital=capital)}

        for name, r in results.items():
            st.subheader(f"Split: {name}")
            m = r.metrics
            status = m.get("status", "?")
            if status != "ok":
                st.error(f"Status: {status} — not a success. " + " ".join(r.warnings[:1]))
            cols = st.columns(5)
            cols[0].metric("Trades", m.get("trade_count", 0))
            cols[1].metric("Net return", f"{m.get('net_return_pct', 0):.2f}%")
            cols[2].metric("Benchmark (buy&hold)", f"{m.get('benchmark_return_pct', 0):.2f}%")
            cols[3].metric("Max drawdown", f"{m.get('max_drawdown_pct', 0):.2f}%")
            cols[4].metric("Win rate", f"{m.get('win_rate_pct', 0):.1f}%")
            c2cols = st.columns(4)
            c2cols[0].metric("Net P&L", f"₹{m.get('net_pnl', 0):,.2f}")
            c2cols[1].metric("Total costs", f"₹{m.get('total_costs', 0):,.2f}")
            c2cols[2].metric("Profit factor", str(m.get("profit_factor", 0)))
            c2cols[3].metric("Avg holding (bars)", m.get("avg_holding_days", 0))

            if r.equity_curve:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=r.equity_curve, name="Equity"))
                fig.update_layout(height=320, margin=dict(t=20, b=20),
                                  title="Simulated equity curve (net of costs)")
                st.plotly_chart(fig, use_container_width=True)
            if r.trades:
                st.dataframe(r.trades, use_container_width=True, hide_index=True)
            with st.expander("Assumptions & limitations"):
                st.json(r.config)
                for w in r.warnings:
                    st.caption(w)
            run_id = save_backtest_run(conn, r)
            st.caption(f"Run saved to database as run_id={run_id}.")
