"""OHLCV integrity validation.

Never fabricates prices. Invalid rows are dropped (and counted); structural
problems produce warnings that surface to the user and can force NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

CLEAN_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


@dataclass
class ValidationReport:
    ok: bool = False
    total_rows: int = 0
    valid_rows: int = 0
    dropped_invalid_numeric: int = 0
    dropped_invalid_ohlc: int = 0
    dropped_invalid_ts: int = 0
    duplicates_removed: int = 0
    non_positive_price_rows: int = 0
    negative_volume_rows: int = 0
    sorted: bool = False
    date_start: str | None = None
    date_end: str | None = None
    missing_sessions_gaps: int = 0
    stale_days: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "dropped_invalid_numeric": self.dropped_invalid_numeric,
            "dropped_invalid_ohlc": self.dropped_invalid_ohlc,
            "dropped_invalid_ts": self.dropped_invalid_ts,
            "duplicates_removed": self.duplicates_removed,
            "missing_sessions_gaps": self.missing_sessions_gaps,
            "stale_days": self.stale_days,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def validate_ohlcv(
    df: pd.DataFrame,
    *,
    daily: bool = True,
    stale_after_days: int = 7,
    today: date | None = None,
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate a raw OHLCV frame. Returns (clean_df, report)."""
    rep = ValidationReport(total_rows=len(df))
    if df is None or len(df) == 0:
        rep.errors.append("No rows to validate (empty dataset).")
        return pd.DataFrame(columns=CLEAN_COLUMNS), rep

    work = df.copy()
    # Timestamp validity
    ts_ok = work["ts"].notna()
    rep.dropped_invalid_ts = int((~ts_ok).sum())
    work = work[ts_ok]

    # Numeric validity
    numeric = ["open", "high", "low", "close", "volume"]
    num_ok = work[numeric].notna().all(axis=1)
    rep.dropped_invalid_numeric = int((~num_ok).sum())
    work = work[num_ok]

    if len(work) == 0:
        rep.errors.append("All rows were invalid (timestamps or numbers).")
        return pd.DataFrame(columns=CLEAN_COLUMNS), rep

    # Positive prices and non-negative volume
    price_ok = (work[["open", "high", "low", "close"]] > 0).all(axis=1)
    rep.non_positive_price_rows = int((~price_ok).sum())
    vol_ok = work["volume"] >= 0
    rep.negative_volume_rows = int((~vol_ok).sum())
    work = work[price_ok & vol_ok]

    # OHLC relationships
    hi_bound = work[["open", "close", "low"]].max(axis=1)
    lo_bound = work[["open", "close", "high"]].min(axis=1)
    ohlc_ok = (work["high"] >= hi_bound) & (work["low"] <= lo_bound) & (work["high"] >= work["low"])
    rep.dropped_invalid_ohlc = int((~ohlc_ok).sum())
    work = work[ohlc_ok]

    if len(work) == 0:
        rep.errors.append("All rows failed price/volume/OHLC checks.")
        return pd.DataFrame(columns=CLEAN_COLUMNS), rep

    # Duplicates and ordering
    before = len(work)
    work = work.drop_duplicates(subset=["ts"], keep="last")
    rep.duplicates_removed = before - len(work)
    if not work["ts"].is_monotonic_increasing:
        work = work.sort_values("ts").reset_index(drop=True)
        rep.sorted = True

    work = work[CLEAN_COLUMNS].reset_index(drop=True)
    rep.valid_rows = len(work)
    rep.date_start = str(work["ts"].iloc[0])
    rep.date_end = str(work["ts"].iloc[-1])

    # Gap detection (missing weekday sessions; holidays unknown → warning only)
    if daily and len(work) >= 2:
        idx = pd.to_datetime(work["ts"])
        missing = 0
        for prev, nxt in zip(idx[:-1], idx[1:], strict=False):
            span = pd.bdate_range(prev + pd.Timedelta(days=1), nxt - pd.Timedelta(days=1))
            missing += len(span)
        rep.missing_sessions_gaps = int(missing)
        if missing:
            rep.warnings.append(
                f"{missing} weekday session(s) missing between candles "
                "(could be holidays or data gaps — not filled automatically)."
            )

    # Staleness (tolerates unparseable ts strings — flag instead of crash)
    if rep.date_end:
        try:
            last = pd.Timestamp(str(rep.date_end)[:10])
            ref = pd.Timestamp(today) if today else pd.Timestamp.now().normalize()
            rep.stale_days = int((ref - last).days)
            if rep.stale_days > stale_after_days:
                rep.warnings.append(
                    f"Data is {rep.stale_days} day(s) old (limit {stale_after_days}). "
                    "Signals from this data are marked stale."
                )
        except (ValueError, TypeError):
            rep.warnings.append("Could not parse the last candle timestamp for staleness check.")

    rep.ok = len(rep.errors) == 0 and rep.valid_rows > 0
    return work, rep
