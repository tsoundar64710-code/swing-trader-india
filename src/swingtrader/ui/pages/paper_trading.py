"""Paper Trading page: simulated orders, positions, stop/target monitoring."""

from __future__ import annotations

import sqlite3

import streamlit as st

from swingtrader.core.errors import OrderError
from swingtrader.core.settings import AppSettings
from swingtrader.data.store import find_instrument, load_candles
from swingtrader.paper.engine import PaperEngine


def render(conn: sqlite3.Connection, settings: AppSettings) -> None:
    st.title("Paper Trading")
    st.caption(
        "Simulated execution only. Fills use your imported historical prices + a "
        "slippage assumption — they are NOT real Groww executions."
    )
    engine = PaperEngine(conn, settings)

    c1, c2, c3, c4 = st.columns(4)
    prices: dict[str, float] = {}
    for p in engine.positions():
        iid = _iid(conn, p["symbol"])
        if not iid:
            continue
        df = load_candles(conn, iid)
        if len(df):
            prices[p["symbol"]] = float(df["close"].iloc[-1])
    c1.metric("Simulated cash", f"₹{engine.cash():,.2f}")
    c2.metric("Portfolio equity", f"₹{engine.equity(prices):,.2f}")
    c3.metric("Realized P&L (all time)", f"₹{engine.realized_pnl_total():,.2f}")
    c4.metric("Open positions", len(engine.positions()))

    st.subheader("Place simulated order")
    with st.form("order"):
        f1, f2, f3 = st.columns(3)
        symbol = f1.text_input("Symbol", max_chars=30).strip().upper()
        side = f2.selectbox("Side", ["BUY", "SELL"])
        qty = f3.number_input("Quantity (whole shares)", min_value=1, value=1, step=1)
        ref = st.number_input(
            "Reference price (₹) — defaults to your judgement / last close",
            min_value=0.01, value=100.0, step=0.05,
        )
        notes = st.text_input("Notes (optional)")
        submitted = st.form_submit_button("Submit simulated order", type="primary")
    if submitted:
        if not symbol:
            st.error("Symbol required.")
        else:
            try:
                r = engine.place_market_order(
                    symbol, side, int(qty), ref_price=float(ref), notes=notes or None
                )
                if r["status"] == "FILLED":
                    st.success(
                        f"SIMULATED fill: {side} {qty} {symbol} @ ₹{r['fill_price']:.2f} "
                        "(with slippage). Not a real trade."
                    )
                    st.rerun()
                else:
                    st.error(f"Rejected: {r['reason']}")
            except OrderError as exc:
                st.error(str(exc))

    st.subheader("Open positions")
    positions = engine.positions()
    if positions:
        rows = []
        for p in positions:
            last = prices.get(p["symbol"])
            mv = last * p["qty"] if last else None
            rows.append(
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "avg cost": round(p["avg_cost"], 2),
                    "last price": last,
                    "market value": round(mv, 2) if mv else None,
                    "unrealized P&L": round(mv - p["avg_cost"] * p["qty"], 2) if mv else None,
                    "stop": p["stop_price"],
                    "target": p["target_price"],
                    "opened": (p["opened_at"] or "")[:10],
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.subheader("Manage position")
        pick = st.selectbox("Position", [p["symbol"] for p in positions])
        g1, g2, g3 = st.columns(3)
        stop = g1.number_input("Stop price (₹)", 0.0, 1_000_000.0, 0.0, 0.05)
        target = g2.number_input("Target price (₹)", 0.0, 1_000_000.0, 0.0, 0.05)
        if g3.button("Save stop/target"):
            conn.execute(
                "UPDATE positions SET stop_price=?, target_price=? WHERE symbol=?",
                (stop or None, target or None, pick),
            )
            conn.commit()
            st.success("Saved.")
        if st.button(f"Close position in {pick} at last close"):
            last_prices = prices.get(pick)
            if not last_prices:
                st.error("No market data to price the exit.")
            else:
                try:
                    engine.close_position(pick, last_prices, reason="manual_close")
                    st.success("Position closed (simulated).")
                    st.rerun()
                except OrderError as exc:
                    st.error(str(exc))
        if st.button("Run stop/target monitor on latest bars"):
            bars = {}
            for p in positions:
                iid = _iid(conn, p["symbol"])
                if not iid:
                    continue
                df = load_candles(conn, iid)
                if len(df):
                    last_row = df.iloc[-1]
                    bars[p["symbol"]] = {
                        "open": float(last_row["open"]),
                        "high": float(last_row["high"]),
                        "low": float(last_row["low"]),
                        "close": float(last_row["close"]),
                    }
            exits = engine.check_stop_target_exits(bars)
            if exits:
                for x in exits:
                    st.warning(
                        f"Simulated {x['trigger']} exit: {x['symbol']} @ ₹{x['fill_price']:.2f}"
                    )
            else:
                st.info("No stop/target triggered on the latest bars.")
    else:
        st.info("No open positions.")

    st.subheader("Order history")
    orders = engine.orders()
    if orders:
        st.dataframe(
            [
                {
                    "id": o["id"], "ts": (o["ts"] or "")[:19], "symbol": o["symbol"],
                    "side": o["side"], "qty": o["qty"], "status": o["status"],
                    "reason": o["reason"], "notes": o["notes"],
                }
                for o in orders
            ],
            use_container_width=True, hide_index=True,
        )
    rep = engine.reconcile()
    if rep["ok"]:
        st.success(f"Reconciliation OK — cash ledger consistent (₹{rep['cash']:,.2f}).")
    else:
        st.error("Reconciliation problems: " + "; ".join(rep["problems"]))


def _iid(conn: sqlite3.Connection, symbol: str) -> int | None:
    inst = find_instrument(conn, symbol)
    return inst["id"] if inst else None
