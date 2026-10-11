"""Persistence for instruments, watchlist, candles and import metadata."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from swingtrader.core.errors import DataValidationError
from swingtrader.data.validator import CLEAN_COLUMNS, ValidationReport

VALID_EXCHANGES = {"NSE", "BSE"}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not s or len(s) > 30 or not all(ch.isalnum() or ch in ".-&" for ch in s):
        raise DataValidationError(
            f"Invalid symbol {symbol!r}. Use letters, digits, '.', '-', '&' (max 30)."
        )
    return s


def sanitize_exchange(exchange: str) -> str:
    e = exchange.strip().upper()
    if e not in VALID_EXCHANGES:
        allowed = ", ".join(sorted(VALID_EXCHANGES))
        raise DataValidationError(f"Unsupported exchange {exchange!r}. Allowed: {allowed}.")
    return e


def get_or_create_instrument(
    conn: sqlite3.Connection, symbol: str, exchange: str = "NSE", name: str | None = None
) -> int:
    sym, exch = sanitize_symbol(symbol), sanitize_exchange(exchange)
    row = conn.execute(
        "SELECT id FROM instruments WHERE symbol=? AND exchange=?", (sym, exch)
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO instruments(symbol, exchange, name, created_at) VALUES (?,?,?,?)",
        (sym, exch, name, utcnow()),
    )
    return int(cur.lastrowid)


def save_import(
    conn: sqlite3.Connection,
    instrument_id: int,
    clean_df: pd.DataFrame,
    report: ValidationReport,
    *,
    interval: str = "1d",
    timezone_name: str = "Asia/Kolkata",
    source_name: str = "user-csv",
    source_type: str = "csv",
    adjusted: str = "unknown",
) -> int:
    """Persist validated candles + import metadata atomically. Upserts candles."""
    if clean_df is None or len(clean_df) == 0:
        raise DataValidationError("Refusing to save an empty validated dataset.")
    if list(clean_df.columns) != CLEAN_COLUMNS:
        raise DataValidationError("Validated data has unexpected columns.")
    with conn:
        src_row = conn.execute(
            "SELECT id FROM data_sources WHERE name=? AND source_type=?",
            (source_name, source_type),
        ).fetchone()
        if src_row:
            source_id = int(src_row["id"])
        else:
            source_id = int(
                conn.execute(
                    "INSERT INTO data_sources(name, source_type, config_json, created_at) "
                    "VALUES (?,?,?,?)",
                    (source_name, source_type, "{}", utcnow()),
                ).lastrowid
            )
        cur = conn.execute(
            """INSERT INTO candle_imports
               (instrument_id, source_id, interval, timezone, imported_at, row_count,
                date_start, date_end, adjusted, validation_status, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                instrument_id,
                source_id,
                interval,
                timezone_name,
                utcnow(),
                int(len(clean_df)),
                report.date_start,
                report.date_end,
                adjusted,
                "ok" if report.ok else "failed",
                json.dumps(report.warnings),
            ),
        )
        import_id = int(cur.lastrowid)
        conn.executemany(
            """INSERT INTO candles(instrument_id, ts, open, high, low, close, volume, import_id)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(instrument_id, ts) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume, import_id=excluded.import_id""",
            [
                (instrument_id, r.ts, r.open, r.high, r.low, r.close, r.volume, import_id)
                for r in clean_df.itertuples(index=False)
            ],
        )
    return import_id


def load_candles(conn: sqlite3.Connection, instrument_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT ts, open, high, low, close, volume FROM candles
           WHERE instrument_id=? ORDER BY ts""",
        conn,
        params=(instrument_id,),
    )
    return df


def instrument_info(conn: sqlite3.Connection, instrument_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM instruments WHERE id=?", (instrument_id,)).fetchone()
    return dict(row) if row else None


def find_instrument(conn: sqlite3.Connection, symbol: str, exchange: str = "NSE") -> dict | None:
    row = conn.execute(
        "SELECT * FROM instruments WHERE symbol=? AND exchange=?",
        (sanitize_symbol(symbol), sanitize_exchange(exchange)),
    ).fetchone()
    return dict(row) if row else None


def add_to_watchlist(conn: sqlite3.Connection, instrument_id: int) -> None:
    n = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist(instrument_id, position, added_at) VALUES (?,?,?)",
            (instrument_id, int(n), utcnow()),
        )


def remove_from_watchlist(conn: sqlite3.Connection, instrument_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM watchlist WHERE instrument_id=?", (instrument_id,))


def list_watchlist(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT i.id, i.symbol, i.exchange, i.name, w.added_at,
                  (SELECT MAX(ts) FROM candles c WHERE c.instrument_id=i.id) AS last_candle_ts,
                  (SELECT COUNT(*) FROM candles c WHERE c.instrument_id=i.id) AS candle_count
           FROM watchlist w JOIN instruments i ON i.id = w.instrument_id
           ORDER BY w.position, i.symbol"""
    ).fetchall()
    return [dict(r) for r in rows]


def list_imports(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT ci.*, i.symbol, i.exchange, ds.name AS source_name
           FROM candle_imports ci
           JOIN instruments i ON i.id = ci.instrument_id
           LEFT JOIN data_sources ds ON ds.id = ci.source_id
           ORDER BY ci.imported_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _csv_safe(value: str) -> str:
    """Neutralize CSV formula injection on export."""
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_watchlist_csv(conn: sqlite3.Connection, path) -> int:
    """Export watchlist with CSV-injection precautions. Returns row count."""
    p = Path(path)
    rows = list_watchlist(conn)
    df = pd.DataFrame(
        [
            {
                "symbol": _csv_safe(r["symbol"]),
                "exchange": _csv_safe(r["exchange"]),
                "name": _csv_safe(r["name"] or ""),
                "last_candle_ts": _csv_safe(r["last_candle_ts"] or ""),
                "candle_count": r["candle_count"],
                "added_at": r["added_at"],
            }
            for r in rows
        ]
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return len(df)
