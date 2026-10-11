"""Market-data loader/validator/store tests.

All price fixtures are SYNTHETIC (deterministic random walk) and do not
represent real securities.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swingtrader.core.errors import DataValidationError
from swingtrader.data.loader import load_ohlcv_csv
from swingtrader.data.store import (
    add_to_watchlist,
    export_watchlist_csv,
    find_instrument,
    get_or_create_instrument,
    list_watchlist,
    load_candles,
    remove_from_watchlist,
    save_import,
)
from swingtrader.data.validator import validate_ohlcv

RNG = np.random.default_rng(42)  # SYNTHETIC data only


def synth_ohlcv(n: int = 120, start: str = "2025-01-01", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.5, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.5, n)
    vol = rng.integers(10_000, 500_000, n).astype(float)
    return pd.DataFrame(
        {
            "ts": [d.strftime("%Y-%m-%d") for d in dates],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    out = df.rename(columns={"ts": "Date"}).copy()
    return out.to_csv(index=False).encode()


# ---------------------------------------------------------------- loader


def test_load_valid_csv_bytes() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(30)))
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 30


def test_load_empty_file_rejected() -> None:
    with pytest.raises(DataValidationError):
        load_ohlcv_csv(b"")


def test_load_header_only_rejected() -> None:
    with pytest.raises(DataValidationError):
        load_ohlcv_csv(b"Date,Open,High,Low,Close,Volume\n")


def test_load_corrupt_file_rejected() -> None:
    with pytest.raises(DataValidationError):
        load_ohlcv_csv(b"\x00\x01\x02,binary,junk\x00\xff")


def test_load_missing_column_rejected() -> None:
    bad = b"Date,Open,Close\n2025-01-01,1,2\n"
    with pytest.raises(DataValidationError, match="Missing required column"):
        load_ohlcv_csv(bad)


def test_load_size_limit_enforced() -> None:
    data = to_csv_bytes(synth_ohlcv(50))
    with pytest.raises(DataValidationError, match="MB"):
        load_ohlcv_csv(data, max_mb=0.000001)


def test_load_row_limit_enforced() -> None:
    with pytest.raises(DataValidationError, match="safety limit"):
        load_ohlcv_csv(to_csv_bytes(synth_ohlcv(50)), max_rows=10)


def test_load_non_csv_path_rejected(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text("x")
    with pytest.raises(DataValidationError, match="\\.csv"):
        load_ohlcv_csv(p)


# ---------------------------------------------------------------- validator


def test_validator_clean_data_passes() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(60)))
    clean, rep = validate_ohlcv(df, today=date(2025, 6, 1))
    assert rep.ok
    assert rep.valid_rows == 60
    assert rep.dropped_invalid_ohlc == 0
    assert not rep.errors


def test_validator_drops_duplicate_timestamps() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(10)))
    dup = pd.concat([df, df.iloc[[5]]], ignore_index=True)
    clean, rep = validate_ohlcv(dup, today=date(2025, 6, 1))
    assert rep.duplicates_removed == 1
    assert rep.valid_rows == 10
    assert clean["ts"].is_unique


def test_validator_flags_missing_sessions() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(30)))
    gapped = pd.concat([df.iloc[:10], df.iloc[20:]], ignore_index=True)
    _, rep = validate_ohlcv(gapped, today=date(2025, 6, 1))
    assert rep.missing_sessions_gaps > 0
    assert any("missing" in w.lower() for w in rep.warnings)


def test_validator_drops_invalid_ohlc_rows() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(10)))
    df.loc[3, "high"] = df.loc[3, "low"] - 5  # high < low
    df.loc[4, "close"] = -10  # negative price
    clean, rep = validate_ohlcv(df, today=date(2025, 6, 1))
    assert rep.dropped_invalid_ohlc == 1
    assert rep.non_positive_price_rows == 1
    assert rep.valid_rows == 8


def test_validator_sorts_unsorted_data() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(20)))
    shuffled = df.sample(frac=1.0, random_state=1).reset_index(drop=True)
    clean, rep = validate_ohlcv(shuffled, today=date(2025, 6, 1))
    assert rep.sorted
    assert clean["ts"].is_monotonic_increasing


def test_validator_detects_stale_data() -> None:
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(20, start="2024-01-01")))
    _, rep = validate_ohlcv(df, stale_after_days=7, today=date(2026, 10, 11))
    assert rep.stale_days is not None and rep.stale_days > 7
    assert any("old" in w.lower() for w in rep.warnings)


def test_validator_empty_input() -> None:
    empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    clean, rep = validate_ohlcv(empty)
    assert not rep.ok
    assert rep.errors


def test_validator_all_rows_invalid() -> None:
    df = pd.DataFrame(
        {"ts": ["bad", "worse"], "open": [np.nan, np.nan], "high": [1, 1],
         "low": [1, 1], "close": [1, 1], "volume": [1, 1]}
    )
    clean, rep = validate_ohlcv(df)
    assert not rep.ok
    assert len(clean) == 0


# ---------------------------------------------------------------- store


def test_instrument_create_and_find(tmp_db: sqlite3.Connection) -> None:
    iid = get_or_create_instrument(tmp_db, "reliance", "NSE", "Reliance Industries")
    again = get_or_create_instrument(tmp_db, "RELIANCE", "NSE")
    assert iid == again
    found = find_instrument(tmp_db, "RELIANCE")
    assert found and found["id"] == iid
    assert found["name"] == "Reliance Industries"


def test_invalid_symbol_and_exchange_rejected(tmp_db: sqlite3.Connection) -> None:
    with pytest.raises(DataValidationError):
        get_or_create_instrument(tmp_db, "BAD;DROP", "NSE")
    with pytest.raises(DataValidationError):
        get_or_create_instrument(tmp_db, "RELIANCE", "NYSE")


def test_save_and_load_candles_roundtrip(tmp_db: sqlite3.Connection) -> None:
    iid = get_or_create_instrument(tmp_db, "TCS")
    df = load_ohlcv_csv(to_csv_bytes(synth_ohlcv(40)))
    clean, rep = validate_ohlcv(df, today=date(2025, 6, 1))
    imp = save_import(tmp_db, iid, clean, rep, source_name="test-csv")
    assert imp > 0
    loaded = load_candles(tmp_db, iid)
    assert len(loaded) == 40
    assert list(loaded.columns) == ["ts", "open", "high", "low", "close", "volume"]


def test_save_empty_import_rejected(tmp_db: sqlite3.Connection) -> None:
    iid = get_or_create_instrument(tmp_db, "TCS")
    empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    clean, rep = validate_ohlcv(empty)
    with pytest.raises(DataValidationError):
        save_import(tmp_db, iid, clean, rep)


def test_watchlist_add_remove_list(tmp_db: sqlite3.Connection) -> None:
    a = get_or_create_instrument(tmp_db, "INFY")
    b = get_or_create_instrument(tmp_db, "HDFCBANK")
    add_to_watchlist(tmp_db, a)
    add_to_watchlist(tmp_db, b)
    add_to_watchlist(tmp_db, a)  # idempotent
    assert len(list_watchlist(tmp_db)) == 2
    remove_from_watchlist(tmp_db, a)
    remaining = list_watchlist(tmp_db)
    assert len(remaining) == 1 and remaining[0]["symbol"] == "HDFCBANK"


def test_export_watchlist_sanitizes_formulas(tmp_db: sqlite3.Connection, tmp_path: Path) -> None:
    iid = get_or_create_instrument(tmp_db, "-BAD")  # valid symbol chars, but CSV-unsafe prefix
    add_to_watchlist(tmp_db, iid)
    out = tmp_path / "wl.csv"
    n = export_watchlist_csv(tmp_db, out)
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "'-BAD" in text  # neutralized with leading apostrophe
