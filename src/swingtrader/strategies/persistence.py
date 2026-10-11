"""Signal persistence for auditability."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from swingtrader.strategies.signals import SignalResult


def save_signal(conn: sqlite3.Connection, instrument_id: int, sig: SignalResult) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO signals
               (instrument_id, strategy_id, signal_ts, data_ts, action, details_json, created_at)
               VALUES (?, NULL, ?, ?, ?, ?, ?)""",
            (
                instrument_id,
                sig.signal_ts,
                sig.data_ts,
                sig.action,
                sig.to_details_json(),
                datetime.now(UTC).isoformat(),
            ),
        )
        return int(cur.lastrowid)


def latest_signals(conn: sqlite3.Connection, instrument_id: int | None = None) -> list[dict]:
    q = (
        "SELECT s.*, i.symbol, i.exchange FROM signals s "
        "JOIN instruments i ON i.id = s.instrument_id"
    )
    params: tuple = ()
    if instrument_id is not None:
        q += " WHERE s.instrument_id=?"
        params = (instrument_id,)
    q += " ORDER BY s.id DESC LIMIT 100"
    return [dict(r) for r in conn.execute(q, params).fetchall()]
