"""CSV OHLCV loading with safety limits.

Accepted columns (case-insensitive; first match wins):
  timestamp: date | datetime | timestamp | time
  OHLCV:     open, high, low, close, volume
Dates are interpreted as Asia/Kolkata calendar dates for daily bars and stored
as ISO strings (YYYY-MM-DD for daily).
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from swingtrader.core.errors import DataValidationError

_TS_ALIASES = ("timestamp", "datetime", "date", "time")
_OHLCV_ALIASES = {
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "last"),
    "volume": ("volume", "vol", "v"),
}


def _read_bytes(data: bytes, max_mb: float) -> pd.DataFrame:
    if len(data) > max_mb * 1024 * 1024:
        raise DataValidationError(
            f"CSV exceeds the {max_mb:.0f} MB import limit. Split the file or "
            "raise data.max_import_file_mb in Settings if you trust the source."
        )
    if len(data) == 0:
        raise DataValidationError("CSV file is empty.")
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pandas raises many parse error types
        raise DataValidationError(f"Could not parse CSV: {exc}") from exc


def _read_path(path: Path, max_mb: float) -> pd.DataFrame:
    if path.suffix.lower() != ".csv":
        raise DataValidationError("Only .csv files are accepted.")
    if not path.is_file():
        raise DataValidationError(f"File not found: {path.name}")
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise DataValidationError(f"CSV exceeds the {max_mb:.0f} MB import limit.")
    try:
        return pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise DataValidationError(f"Could not parse CSV: {exc}") from exc


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower().strip(): c for c in df.columns}
    ts_col = next((cols[a] for a in _TS_ALIASES if a in cols), None)
    if ts_col is None:
        raise DataValidationError(
            "No timestamp column found. Expected one of: Date, Timestamp, Datetime, Time."
        )
    out = pd.DataFrame()
    out["ts"] = df[ts_col]
    for target, aliases in _OHLCV_ALIASES.items():
        src = next((cols[a] for a in aliases if a in cols), None)
        if src is None:
            raise DataValidationError(f"Missing required column: {target}")
        out[target] = df[src]
    return out


def load_ohlcv_csv(
    source: bytes | Path,
    *,
    max_mb: float = 50.0,
    max_rows: int = 500_000,
    daily: bool = True,
) -> pd.DataFrame:
    """Load a CSV into a raw OHLCV frame. Validation happens separately."""
    if isinstance(source, (bytes, bytearray)):
        raw = _read_bytes(bytes(source), max_mb)
    else:
        raw = _read_path(Path(source), max_mb)
    if len(raw) == 0:
        raise DataValidationError("CSV has a header but no data rows.")
    if len(raw) > max_rows:
        raise DataValidationError(
            f"CSV has {len(raw):,} rows, above the {max_rows:,} safety limit."
        )
    df = _map_columns(raw)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", format="mixed" if daily else None)
    if daily:
        df["ts"] = df["ts"].dt.normalize().dt.strftime("%Y-%m-%d")
    else:
        df["ts"] = df["ts"].dt.tz_localize(None).astype(str)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
