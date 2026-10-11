"""Shared fixtures. All candle fixtures are SYNTHETIC and labelled as such."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swingtrader.core.settings import AppSettings  # noqa: E402
from swingtrader.db.database import init_database  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path):
    conn = init_database(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture()
def settings() -> AppSettings:
    return AppSettings()
