"""Deterministic technical indicators. No look-ahead: every value at index i
uses only rows <= i."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    if n < 1:
        raise ValueError("n must be >= 1")
    return series.rolling(window=n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    if n < 1:
        raise ValueError("n must be >= 1")
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    if n < 2:
        raise ValueError("n must be >= 2")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain.notna() & avg_loss.notna())
    return out


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing). Expects open/high/low/close."""
    if n < 1:
        raise ValueError("n must be >= 1")
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rolling_low(df: pd.DataFrame, n: int) -> pd.Series:
    """Rolling n-day low of the `low` column (support context)."""
    return df["low"].rolling(window=n, min_periods=n).min()


def rolling_high(df: pd.DataFrame, n: int) -> pd.Series:
    return df["high"].rolling(window=n, min_periods=n).max()


def add_indicators(df: pd.DataFrame, params) -> pd.DataFrame:
    """Attach indicator columns used by strategies/research. Returns a copy."""
    out = df.copy()
    out["sma_fast"] = sma(out["close"], params.sma_fast)
    out["sma_slow"] = sma(out["close"], params.sma_slow)
    out["rsi"] = rsi(out["close"], params.rsi_period)
    out["atr"] = atr(out, params.atr_period)
    out["vol_sma"] = sma(out["volume"], params.volume_sma_period)
    out["sup_20"] = rolling_low(out, 20)
    out["res_20"] = rolling_high(out, 20)
    return out
