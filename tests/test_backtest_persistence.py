"""Backtest persistence test."""

from __future__ import annotations

import sqlite3

from swingtrader.backtest.engine import run_backtest
from swingtrader.backtest.persistence import save_backtest_run
from swingtrader.core.settings import AppSettings
from tests.test_backtest import cycle_data


def test_backtest_run_saved(tmp_db: sqlite3.Connection) -> None:
    res = run_backtest(cycle_data(2), AppSettings(), symbol="SYN")
    run_id = save_backtest_run(tmp_db, res)
    assert run_id > 0
    row = tmp_db.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == res.metrics["status"]
    n_trades = tmp_db.execute(
        "SELECT COUNT(*) FROM backtest_trades WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    assert n_trades == len(res.trades)
