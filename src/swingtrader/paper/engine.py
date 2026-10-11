"""Simulated order/position engine. NEVER submits real orders.

Documented fill assumptions:
  - MARKET orders fill at the reference price provided by the caller
    (typically the latest verified close), worsened by the configured
    slippage percentage.
  - Historical candles cannot establish the exact price a real order would
    have filled at; all fills are simulations.
  - Duplicate client order IDs are rejected (unique DB constraint).
  - Cash can never go negative; sells can never exceed held quantity.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from swingtrader.core.errors import OrderError
from swingtrader.core.settings import AppSettings
from swingtrader.costs.engine import apply_slippage, estimate_costs
from swingtrader.db.database import transaction


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PaperEngine:
    def __init__(self, conn: sqlite3.Connection, settings: AppSettings):
        self.conn = conn
        self.settings = settings
        self._ensure_capital()

    # ------------------------------------------------------------- capital
    def _ensure_capital(self) -> None:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cash_ledger WHERE kind='INITIAL'"
        ).fetchone()[0]
        if row == 0:
            amount = self.settings.initial_capital_inr
            with transaction(self.conn) as c:
                c.execute(
                    "INSERT INTO cash_ledger(ts, amount, kind, balance_after, note) "
                    "VALUES (?,?,?,?,?)",
                    (_now(), amount, "INITIAL", amount, "Simulated starting capital"),
                )

    def cash(self) -> float:
        row = self.conn.execute(
            "SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return float(row["balance_after"]) if row else 0.0

    def _ledger(self, amount: float, kind: str, ref_id: int | None, note: str) -> float:
        bal = self.cash() + amount
        if bal < -1e-6:
            raise OrderError("Transaction would make cash negative — rejected.")
        self.conn.execute(
            "INSERT INTO cash_ledger(ts, amount, kind, ref_id, balance_after, note) "
            "VALUES (?,?,?,?,?,?)",
            (_now(), amount, kind, ref_id, bal, note),
        )
        return bal

    # ------------------------------------------------------------- orders
    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        *,
        ref_price: float,
        notes: str | None = None,
        client_order_id: str | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        """Create and immediately simulate a fill at ref_price (+ slippage)."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise OrderError("Side must be BUY or SELL.")
        if qty < 1:
            raise OrderError("Quantity must be a whole number >= 1.")
        if ref_price <= 0:
            raise OrderError("Reference price must be positive.")
        if side == "BUY" and self.trading_blocked_by_daily_loss():
            pnl = self.realized_pnl_today()
            limit = self.daily_loss_limit_inr()
            raise OrderError(
                f"Daily loss limit reached: today's realized P&L is ₹{pnl:,.2f} "
                f"(threshold -₹{limit:,.2f}). New BUY orders are blocked until "
                f"the next session per loss_cooldown_sessions."
            )
        cid = client_order_id or uuid.uuid4().hex
        fill_price = apply_slippage(ref_price, side, self.settings.costs)

        try:
            with transaction(self.conn) as c:
                cur = c.execute(
                    """INSERT INTO orders
                       (client_order_id, ts, symbol, side, qty, order_type, limit_price,
                        status, reason, notes, created_at)
                       VALUES (?,?,?,? ,?, 'MARKET', NULL, 'PENDING', NULL, ?, ?)""",
                    (cid, ts or _now(), symbol, side, qty, notes, _now()),
                )
                order_id = int(cur.lastrowid)
                self._execute_fill(c, order_id, symbol, side, qty, fill_price, ts or _now())
                status = c.execute(
                    "SELECT status, reason FROM orders WHERE id=?", (order_id,)
                ).fetchone()
            return {
                "order_id": order_id,
                "client_order_id": cid,
                "status": status["status"],
                "reason": status["reason"],
                "fill_price": fill_price if status["status"] == "FILLED" else None,
                "qty": qty,
                "side": side,
                "symbol": symbol,
                "simulated": True,
            }
        except sqlite3.IntegrityError as exc:
            if "client_order_id" in str(exc).lower() or "unique" in str(exc).lower():
                raise OrderError(
                    f"Duplicate client order id {cid!r} — order ignored (dedupe protection)."
                ) from exc
            raise

    def _execute_fill(
        self,
        c: sqlite3.Connection,
        order_id: int,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        ts: str,
    ) -> None:
        """Must run inside a transaction. Updates cash, position, fill, order."""
        notional = price * qty
        costs = estimate_costs(notional, side, self.settings.costs)
        if side == "BUY":
            total = notional + costs["total"]
            if total > self.cash() + 1e-6:
                c.execute(
                    "UPDATE orders SET status='REJECTED', reason=? WHERE id=?",
                    (f"Insufficient cash: need ₹{total:,.2f}, have ₹{self.cash():,.2f}", order_id),
                )
                return
            self._ledger(-total, "BUY", order_id, f"BUY {qty} {symbol} @ {price:.2f}")
            row = c.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            if row:
                new_qty = int(row["qty"]) + qty
                new_avg = (row["avg_cost"] * row["qty"] + notional + costs["total"]) / new_qty
                c.execute(
                    "UPDATE positions SET qty=?, avg_cost=? WHERE symbol=?",
                    (new_qty, new_avg, symbol),
                )
            else:
                c.execute(
                    "INSERT INTO positions(symbol, qty, avg_cost, opened_at) VALUES (?,?,?,?)",
                    (symbol, qty, (notional + costs["total"]) / qty, ts),
                )
            pnl = None
        else:  # SELL
            row = c.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            held = int(row["qty"]) if row else 0
            if qty > held:
                c.execute(
                    "UPDATE orders SET status='REJECTED', reason=? WHERE id=?",
                    (f"Cannot sell {qty}; only {held} held.", order_id),
                )
                return
            proceeds = notional - costs["total"]
            avg = float(row["avg_cost"])
            pnl = (price - avg) * qty - costs["total"]
            self._ledger(proceeds, "SELL", order_id, f"SELL {qty} {symbol} @ {price:.2f}")
            remaining = held - qty
            if remaining == 0:
                c.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            else:
                c.execute(
                    "UPDATE positions SET qty=? WHERE symbol=?", (remaining, symbol)
                )
        c.execute(
            """INSERT INTO fills(order_id, ts, price, qty, brokerage, taxes_fees,
                                 slippage, pnl_realized)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                order_id, ts, price, qty, costs["brokerage"],
                round(costs["total"] - costs["brokerage"], 2),
                0.0, None if pnl is None else round(pnl, 2),
            ),
        )
        c.execute("UPDATE orders SET status='FILLED' WHERE id=?", (order_id,))

    def cancel_order(self, order_id: int) -> bool:
        with transaction(self.conn) as c:
            row = c.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                raise OrderError(f"Order {order_id} not found.")
            if row["status"] != "PENDING":
                raise OrderError(f"Only PENDING orders can be cancelled (is {row['status']}).")
            c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (order_id,))
        return True

    # ------------------------------------------------------------- views
    def positions(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
        ]

    def orders(self, limit: int = 100) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        ]

    def realized_pnl_today(self) -> float:
        """Sum of realized P&L from fills dated today (UTC)."""
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) FROM fills "
            "WHERE pnl_realized IS NOT NULL AND ts LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return float(row[0])

    def daily_loss_limit_inr(self) -> float:
        """Absolute INR daily-loss threshold from percentage of current equity."""
        equity = self.equity({})
        return equity * self.settings.risk.daily_loss_limit_pct / 100

    def trading_blocked_by_daily_loss(self) -> bool:
        """True when today's realized losses have hit the configured threshold."""
        pnl = self.realized_pnl_today()
        limit = self.daily_loss_limit_inr()
        return pnl <= -limit + 1e-6

    def equity(self, price_lookup: dict[str, float]) -> float:
        mv = sum(
            price_lookup.get(p["symbol"], p["avg_cost"]) * p["qty"]
            for p in self.positions()
        )
        return self.cash() + mv

    def realized_pnl_total(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) FROM fills WHERE pnl_realized IS NOT NULL"
        ).fetchone()
        return float(row[0])

    # ---------------------------------------------------- stop/target exits
    def close_position(
        self,
        symbol: str,
        ref_price: float,
        *,
        reason: str = "manual",
        ts: str | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT qty FROM positions WHERE symbol=?", (symbol,)
        ).fetchone()
        if not row or int(row["qty"]) < 1:
            raise OrderError(f"No open position in {symbol}.")
        return self.place_market_order(
            symbol, "SELL", int(row["qty"]), ref_price=ref_price,
            notes=reason, ts=ts,
        )

    def check_stop_target_exits(
        self,
        bars: dict[str, dict[str, float]],
    ) -> list[dict[str, Any]]:
        """bars: symbol -> latest bar dict with at least low/high/open keys."""
        triggered = []
        for p in self.positions():
            bar = bars.get(p["symbol"])
            if not bar:
                continue
            ref = None
            reason = None
            if p["stop_price"] is not None and bar.get("low", 1e18) <= p["stop_price"]:
                ref = min(bar.get("open", p["stop_price"]), p["stop_price"])
                reason = "stop"
            elif p["target_price"] is not None and bar.get("high", 0) >= p["target_price"]:
                ref = p["target_price"]
                reason = "target"
            if ref and reason:
                r = self.close_position(p["symbol"], ref, reason=reason)
                r["trigger"] = reason
                triggered.append(r)
        return triggered

    # ------------------------------------------------------------- audit
    def reconcile(self) -> dict[str, Any]:
        """Recompute cash from the ledger; verify invariants."""
        problems: list[str] = []
        total = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM cash_ledger"
        ).fetchone()[0]
        last = self.cash()
        if abs(total - last) > 0.01:
            problems.append(
                f"Cash ledger mismatch: sum(amount)={total:.2f} vs last balance={last:.2f}"
            )
        if last < -1e-6:
            problems.append(f"Negative cash detected: {last:.2f}")
        neg = self.conn.execute(
            "SELECT symbol, qty FROM positions WHERE qty <= 0"
        ).fetchall()
        for r in neg:
            problems.append(f"Non-positive position quantity: {r['symbol']}={r['qty']}")
        orphan = self.conn.execute(
            """SELECT o.id FROM orders o
               LEFT JOIN fills f ON f.order_id = o.id
               WHERE o.status='FILLED' AND f.id IS NULL"""
        ).fetchall()
        for r in orphan:
            problems.append(f"Filled order {r['id']} has no fill record")
        return {"ok": not problems, "cash": last, "problems": problems}
