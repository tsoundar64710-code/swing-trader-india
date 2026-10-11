"""Database migration, backup and restore tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swingtrader.core.errors import MigrationError
from swingtrader.db.database import (
    backup_database,
    connect,
    init_database,
    migrate,
    restore_database,
    transaction,
)
from swingtrader.db.schema import MIGRATIONS


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def test_migrate_creates_all_tables(tmp_db: sqlite3.Connection) -> None:
    tables = _tables(tmp_db)
    expected = {
        "instruments", "watchlist", "candles", "candle_imports", "data_sources",
        "signals", "strategy_configs", "backtest_runs", "backtest_trades",
        "orders", "fills", "positions", "cash_ledger", "journal_entries",
        "cost_config", "audit_log", "app_meta", "schema_migrations",
    }
    assert expected.issubset(tables)


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = init_database(tmp_path / "a.db")
    before = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    again = migrate(conn)
    after = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert again == []
    assert before == after == len(MIGRATIONS)
    conn.close()


def test_transaction_rollback_on_error(tmp_db: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError):
        with transaction(tmp_db) as c:
            c.execute(
                "INSERT INTO instruments(symbol, exchange, created_at) VALUES ('X','NSE','t')"
            )
            raise RuntimeError("boom")
    n = tmp_db.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    assert n == 0


def test_foreign_keys_enforced(tmp_db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO watchlist(instrument_id, added_at) VALUES (999, 't')"
        )


def test_backup_and_restore(tmp_path: Path) -> None:
    db = tmp_path / "live.db"
    conn = init_database(db)
    conn.execute(
        "INSERT INTO instruments(symbol, exchange, created_at) VALUES ('RELIANCE','NSE','t')"
    )
    conn.commit()
    conn.close()

    dest = backup_database(db, tmp_path / "backups")
    assert dest.exists()

    # mutate live db, then restore
    conn = connect(db)
    conn.execute("DELETE FROM instruments")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 0
    conn.close()

    restore_database(dest, db)
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 1
    conn.close()


def test_restore_rejects_corrupt_backup(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database at all........")
    with pytest.raises(MigrationError):
        restore_database(bad, tmp_path / "live.db")


def test_positions_qty_non_negative(tmp_db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO positions(symbol, qty, avg_cost) VALUES ('A', -1, 100)"
        )
