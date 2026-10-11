"""Stock Research page: chart, indicators, transparent signal breakdown."""

from __future__ import annotations

import sqlite3

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from swingtrader.core.settings import AppSettings
from swingtrader.data.store import find_instrument, list_watchlist, load_candles
from swingtrader.strategies.indicators import add_indicators
from swingtrader.strategies.signals import trend_pullback_signal


def _chart(ind) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03
    )
    fig.add_trace(
        go.Candlestick(
            x=ind["ts"], open=ind["open"], high=ind["high"], low=ind["low"], close=ind["close"],
            name="Price",
        ),
        row=1, col=1,
    )
    for col, color in (("sma_fast", "orange"), ("sma_slow", "blue")):
        fig.add_trace(
            go.Scatter(x=ind["ts"], y=ind[col], name=col, line=dict(width=1.5, color=color)),
            row=1, col=1,
        )
    fig.add_trace(
        go.Bar(x=ind["ts"], y=ind["volume"], name="Volume", marker_color="teal"),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=ind["ts"], y=ind["rsi"], name="RSI", line=dict(color="purple")),
        row=3, col=1,
    )
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
    fig.update_layout(height=640, xaxis_rangeslider_visible=False, margin=dict(t=30, b=20))
    return fig


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Stock Research")
    rows = list_watchlist(conn)
    if not rows:
        st.info("Add symbols to the watchlist first.")
        return
    pick = st.selectbox("Symbol", [f"{r['symbol']} ({r['exchange']})" for r in rows])
    sym, _, exch = pick.partition(" (")
    inst = find_instrument(conn, sym, exch.rstrip(")"))
    if not inst:
        st.error("Instrument not found.")
        return
    df = load_candles(conn, inst["id"])
    if len(df) == 0:
        st.error(f"No candles for {sym}. Import a CSV in the Data Centre.")
        return

    sig = trend_pullback_signal(sym, df, settings.strategy)
    ind = add_indicators(df, settings.strategy)
    last = ind.iloc[-1]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Last close", f"₹{last['close']:,.2f}")
    m2.metric("Data as of", sig.data_ts)
    m3.metric("RSI (14)", f"{last['rsi']:.1f}" if last["rsi"] == last["rsi"] else "—")
    m4.metric("ATR (14)", f"{last['atr']:.2f}" if last["atr"] == last["atr"] else "—")

    st.plotly_chart(_chart(ind), use_container_width=True)

    st.subheader(f"Signal: {sig.action}")
    st.caption(
        f"Strategy: {sig.strategy_name} · computed {sig.signal_ts[:19]}Z · "
        f"based on candle {sig.data_ts}"
    )
    if sig.action == "BUY_SETUP":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entry reference", f"₹{sig.entry_reference:,.2f}")
        c2.metric("Stop (ATR-based)", f"₹{sig.stop_price:,.2f}")
        c3.metric("Target (scenario)", f"₹{sig.target_price:,.2f}")
        c4.metric("Reward : Risk", f"{sig.reward_risk:.2f}")
        st.caption(
            "The target is a scenario, not a forecast. A stop does not guarantee the exit "
            "price — gaps can fill far below it, increasing losses. Transaction costs "
            "(brokerage, STT, GST, stamp duty, slippage) further reduce net results."
        )
    for r in sig.reasons:
        st.write("-", r)
    with st.expander("Full rule audit"):
        st.markdown("**Satisfied:** " + (", ".join(sig.rules_satisfied) or "none"))
        st.markdown("**Not satisfied:** " + (", ".join(sig.rules_failed) or "none"))
        st.json(sig.to_details_json())
    with st.expander("Latest indicator values"):
        st.dataframe(
            ind.tail(15)[
                ["ts", "open", "high", "low", "close", "volume",
                 "sma_fast", "sma_slow", "rsi", "atr", "vol_sma", "sup_20", "res_20"]
            ],
            use_container_width=True,
        )

    st.subheader("Position size & cost estimate")
    st.caption("Uses your simulated capital and risk limits. Estimates only — not advice.")
    from swingtrader.costs.engine import cost_warning
    from swingtrader.risk.sizing import PortfolioState, size_position

    col_a, col_b = st.columns(2)
    cash = col_a.number_input(
        "Simulated cash available (₹)", min_value=0.0,
        value=float(settings.initial_capital_inr), step=1000.0,
    )
    open_pos = col_b.number_input("Open positions already held", 0, 50, 0)
    if sig.action == "BUY_SETUP" and sig.entry_reference and sig.stop_price:
        portfolio = PortfolioState(
            equity_inr=cash, cash_inr=cash, open_positions=open_pos, exposure_inr=0.0
        )
        plan = size_position(sig.entry_reference, sig.stop_price, portfolio, settings)
        if plan.accepted:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Suggested quantity", f"{plan.qty} shares")
            s2.metric("Notional", f"₹{plan.notional_inr:,.0f}")
            s3.metric("Est. buy costs", f"₹{plan.est_buy_costs['total']:,.2f}")
            s4.metric("Est. total risk", f"₹{plan.est_total_risk_inr:,.2f}")
            st.caption(
                f"Round-trip cost estimate: ₹{plan.est_round_trip_costs['round_trip_total']:,.2f} "
                f"({plan.est_round_trip_costs['round_trip_pct']:.2f}% of notional)"
            )
        else:
            st.error("Position rejected by risk engine:")
            for r in plan.rejections:
                st.write("-", r)
        for n in plan.notes:
            st.warning(n)
        st.info(cost_warning(settings.costs))
    else:
        st.info("No BUY SETUP on the latest candle — nothing to size.")
