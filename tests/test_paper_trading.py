"""Paper-trading engine tests: accounting invariants, dedupe, restart."""

from __future__ import annotations

import sqlite3

import pytest

from swingtrader.core.errors import OrderError
from swingtrader.core.settings import AppSettings
from swingtrader.db.database import init_database
from swingtrader.paper.engine import PaperEngine


def engine(tmp_db: sqlite3.Connection, capital: float = 100_000.0) -> PaperEngine:
    s = AppSettings(initial_capital_inr=capital)
    return PaperEngine(tmp_db, s)


def test_initial_capital_seeded(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    assert e.cash() == pytest.approx(100_000.0)


def test_buy_then_sell_accounting(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    r = e.place_market_order("TCS", "BUY", 10, ref_price=1000)
    assert r["status"] == "FILLED"
    assert r["fill_price"] > 1000  # slippage worsens the buy
    cash_after_buy = e.cash()
    assert cash_after_buy < 100_000
    pos = e.positions()
    assert len(pos) == 1 and pos[0]["qty"] == 10

    r2 = e.place_market_order("TCS", "SELL", 10, ref_price=1100)
    assert r2["status"] == "FILLED"
    assert r2["fill_price"] < 1100  # slippage worsens the sell
    assert e.positions() == []
    assert e.cash() > cash_after_buy
    assert e.realized_pnl_total() > 0


def test_avg_cost_weighting(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("X", "BUY", 10, ref_price=100)
    e.place_market_order("X", "BUY", 10, ref_price=200)
    pos = e.positions()[0]
    assert pos["qty"] == 20
    # avg includes fees, so slightly above simple mean of 150
    assert 149 < pos["avg_cost"] < 160


def test_insufficient_cash_rejected(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db, capital=1_000)
    r = e.place_market_order("M", "BUY", 100, ref_price=1000)
    assert r["status"] == "REJECTED"
    assert "Insufficient cash" in r["reason"]
    assert e.cash() == pytest.approx(1_000)
    assert e.positions() == []


def test_oversell_rejected(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    r = e.place_market_order("Y", "SELL", 5, ref_price=100)
    assert r["status"] == "REJECTED"
    assert "only 0 held" in r["reason"].lower()


def test_duplicate_client_order_id_rejected(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("Z", "BUY", 1, ref_price=100, client_order_id="abc")
    with pytest.raises(OrderError, match="[Dd]uplicate"):
        e.place_market_order("Z", "BUY", 1, ref_price=100, client_order_id="abc")
    # only one fill happened
    n = tmp_db.execute("SELECT COUNT(*) FROM orders WHERE client_order_id='abc'").fetchone()[0]
    assert n == 1


def test_invalid_qty_and_price_rejected(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    with pytest.raises(OrderError):
        e.place_market_order("A", "BUY", 0, ref_price=100)
    with pytest.raises(OrderError):
        e.place_market_order("A", "BUY", 1, ref_price=-5)
    with pytest.raises(OrderError):
        e.place_market_order("A", "HOLD", 1, ref_price=100)


def test_stop_trigger_closes_position(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("S", "BUY", 10, ref_price=100)
    tmp_db.execute(
        "UPDATE positions SET stop_price=90, target_price=120 WHERE symbol='S'"
    )
    tmp_db.commit()
    exits = e.check_stop_target_exits(
        {"S": {"open": 95, "high": 96, "low": 89, "close": 91}}
    )
    assert len(exits) == 1
    assert exits[0]["trigger"] == "stop"
    assert e.positions() == []


def test_target_trigger_closes_position(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("T", "BUY", 5, ref_price=100)
    tmp_db.execute("UPDATE positions SET stop_price=80, target_price=120 WHERE symbol='T'")
    tmp_db.commit()
    exits = e.check_stop_target_exits(
        {"T": {"open": 110, "high": 121, "low": 109, "close": 118}}
    )
    assert exits and exits[0]["trigger"] == "target"


def test_restart_preserves_state(tmp_path_factory) -> None:
    db_path = tmp_path_factory.mktemp("restart") / "paper.db"
    conn = init_database(db_path)
    e = PaperEngine(conn, AppSettings(initial_capital_inr=50_000))
    e.place_market_order("R", "BUY", 4, ref_price=500)
    cash_before = e.cash()
    conn.close()

    conn2 = init_database(db_path)
    e2 = PaperEngine(conn2, AppSettings(initial_capital_inr=50_000))
    assert e2.cash() == pytest.approx(cash_before)
    assert e2.positions()[0]["symbol"] == "R"
    conn2.close()


def test_reconcile_clean_after_trades(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("C", "BUY", 3, ref_price=300)
    e.place_market_order("C", "SELL", 2, ref_price=310)
    rep = e.reconcile()
    assert rep["ok"], rep["problems"]


def test_reconcile_detects_tampering(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("D", "BUY", 1, ref_price=100)
    # simulate corruption: inject ledger row without matching balance chain
    tmp_db.execute(
        "INSERT INTO cash_ledger(ts, amount, kind, balance_after, note) "
        "VALUES ('t', 999999, 'FAKE', 999999, 'tamper')"
    )
    tmp_db.commit()
    rep = e.reconcile()
    assert not rep["ok"]


def test_fees_recorded_on_fills(tmp_db: sqlite3.Connection) -> None:
    e = engine(tmp_db)
    e.place_market_order("F", "BUY", 10, ref_price=1000)
    fill = tmp_db.execute("SELECT * FROM fills ORDER BY id DESC LIMIT 1").fetchone()
    assert fill["brokerage"] > 0
    assert fill["taxes_fees"] > 0
    order = tmp_db.execute("SELECT status FROM orders").fetchone()
    assert order["status"] == "FILLED"
