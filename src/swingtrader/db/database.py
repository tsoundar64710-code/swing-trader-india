"""SQLite access: connections, migrations, backup/restore helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from swingtrader.core.errors import MigrationError
from swingtrader.core.logging_setup import get_logger
from swingtrader.db.schema import MIGRATIONS

log = get_logger("db")


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane safety defaults."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(r["version"]) for r in rows}


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in order. Returns versions applied."""
    done = applied_versions(conn)
    applied: list[int] = []
    for version, sql in MIGRATIONS:
        if version in done:
            continue
        try:
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",
                    (version, utcnow()),
                )
        except sqlite3.Error as exc:
            raise MigrationError(f"Migration {version} failed: {exc}") from exc
        applied.append(version)
        log.info("Applied migration %s", version)
    return applied


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic unit of work; rolls back on any exception."""
    try:
        with conn:
            yield conn
    except Exception:
        log.exception("Transaction rolled back")
        raise


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    """Create a consistent backup using SQLite's backup API."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"swingtrader-{stamp}.db"
    src = connect(db_path)
    try:
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    # Integrity check on the backup
    chk = sqlite3.connect(str(dest))
    try:
        row = chk.execute("PRAGMA integrity_check").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            dest.unlink(missing_ok=True)
            raise MigrationError(f"Backup integrity check failed: {row}")
    finally:
        chk.close()
    log.info("Backup written: %s", dest)
    return dest


def restore_database(backup_file: Path, db_path: Path) -> None:
    """Restore by copying a verified backup over the live database."""
    chk = sqlite3.connect(str(backup_file))
    try:
        try:
            row = chk.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise MigrationError(
                "Backup file is not a valid database; refusing to restore."
            ) from exc
        if row is None or str(row[0]).lower() != "ok":
            raise MigrationError("Backup file failed integrity check; refusing to restore.")
        applied = {int(r[0]) for r in chk.execute("SELECT version FROM schema_migrations")}
        latest = {v for v, _ in MIGRATIONS}
        if not applied.issuperset(latest):
            raise MigrationError("Backup is from an older schema; migrate it before restoring.")
    finally:
        chk.close()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(backup_file))
    dst = sqlite3.connect(str(db_path))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    log.info("Database restored from %s", backup_file)


def init_database(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    return conn
