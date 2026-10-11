"""Signal persistence test."""

from __future__ import annotations

import sqlite3

import numpy as np

from swingtrader.core.settings import StrategySettings
from swingtrader.data.store import get_or_create_instrument
from swingtrader.strategies.persistence import latest_signals, save_signal
from swingtrader.strategies.signals import trend_pullback_signal
from tests.test_signals import make_df


def test_signal_saved_and_listed(tmp_db: sqlite3.Connection) -> None:
    iid = get_or_create_instrument(tmp_db, "SYN")
    rng = np.random.default_rng(9)
    df = make_df(100 + np.cumsum(rng.normal(0, 1, 80)))
    sig = trend_pullback_signal("SYN", df, StrategySettings())
    sid = save_signal(tmp_db, iid, sig)
    assert sid > 0
    rows = latest_signals(tmp_db, iid)
    assert len(rows) == 1
    assert rows[0]["action"] == sig.action
    assert rows[0]["symbol"] == "SYN"
    assert "entry_reference" in rows[0]["details_json"]
