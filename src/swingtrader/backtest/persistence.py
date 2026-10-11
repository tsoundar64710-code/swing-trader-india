"""Backtest run persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from swingtrader.backtest.engine import BacktestResult


def save_backtest_run(conn: sqlite3.Connection, result: BacktestResult) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO backtest_runs
               (strategy_id, config_json, start_date, end_date, split, status,
                metrics_json, notes, created_at)
               VALUES (NULL,?,?,?,?,?,?,?,?)""",
            (
                json.dumps(result.config, default=str),
                result.dates[0] if result.dates else None,
                result.dates[-1] if result.dates else None,
                str(result.config.get("split", "full")),
                str(result.metrics.get("status", "unknown")),
                json.dumps(result.metrics, default=str),
                json.dumps(result.warnings),
                datetime.now(UTC).isoformat(),
            ),
        )
        run_id = int(cur.lastrowid)
        conn.executemany(
            """INSERT INTO backtest_trades
               (run_id, symbol, entry_ts, entry_price, exit_ts, exit_price, qty,
                costs, pnl, exit_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, t["symbol"], t["entry_ts"], t["entry_price"],
                    t["exit_ts"], t["exit_price"], t["qty"], t["costs"], t["pnl"],
                    t.get("exit_reason"),
                )
                for t in result.trades
            ],
        )
    return run_id
