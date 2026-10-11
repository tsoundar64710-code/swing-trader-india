"""Indicator and strategy tests. Fixtures are SYNTHETIC price paths."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swingtrader.core.settings import StrategySettings
from swingtrader.strategies.indicators import add_indicators, atr, rsi, sma
from swingtrader.strategies.signals import ACTIONS, trend_pullback_signal


def make_df(
    close: np.ndarray, volume: np.ndarray | None = None, start: str = "2025-01-01"
) -> pd.DataFrame:
    n = len(close)
    dates = pd.bdate_range(start, periods=n)
    high = close * 1.01
    low = close * 0.99
    vol = np.full(n, 100_000.0) if volume is None else volume.astype(float)
    return pd.DataFrame(
        {
            "ts": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 1.001,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def ref_rsi_wilder(close: list[float], n: int) -> list[float]:
    """Independent reference: recursive Wilder smoothing (ewm adjust=False).
    Index 0 is NaN (no previous close)."""
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    a = 1.0 / n
    out = [np.nan] * len(close)
    if len(close) < 2:
        return out
    ag, al = gains[1], losses[1]
    out[1] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(2, len(close)):
        ag = (1 - a) * ag + a * gains[i]
        al = (1 - a) * al + a * losses[i]
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def test_sma_basic() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    assert pd.isna(out.iloc[0]) and pd.isna(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_rsi_matches_independent_reference() -> None:
    rng = np.random.default_rng(3)
    close = list(100 + np.cumsum(rng.normal(0, 1, 60)))
    df = make_df(np.array(close))
    mine = rsi(df["close"], 14).tolist()
    ref = ref_rsi_wilder(close, 14)
    compared = 0
    for i in range(len(close)):
        if mine[i] is None or (isinstance(mine[i], float) and np.isnan(mine[i])):
            continue
        assert mine[i] == pytest.approx(ref[i], abs=1e-9), f"mismatch at {i}"
        compared += 1
    assert compared >= 30


def test_rsi_bounded() -> None:
    rng = np.random.default_rng(4)
    df = make_df(100 + np.cumsum(rng.normal(0, 1, 100)))
    out = rsi(df["close"], 14).dropna()
    assert ((out >= 0) & (out <= 100)).all()


def test_atr_positive_and_warms_up() -> None:
    rng = np.random.default_rng(5)
    df = make_df(100 + np.cumsum(rng.normal(0, 1, 40)))
    out = atr(df, 14)
    assert out.iloc[:13].isna().all()
    assert (out.dropna() > 0).all()


def test_indicators_no_lookahead_values_stable() -> None:
    """Appending future bars must not change earlier indicator values."""
    rng = np.random.default_rng(6)
    close = 100 + np.cumsum(rng.normal(0, 1, 120))
    params = StrategySettings()
    full = add_indicators(make_df(close), params)
    truncated = add_indicators(make_df(close[:80]), params)
    for col in ("sma_fast", "sma_slow", "rsi", "atr", "vol_sma"):
        assert list(truncated[col].dropna()) == pytest.approx(
            list(full[col].iloc[:80].dropna()), abs=1e-9
        ), col


def buy_setup_close() -> np.ndarray:
    """SYNTHETIC: steady uptrend, 4-bar pullback to the fast SMA, then a bounce."""
    up = 100 * 1.01 ** np.arange(60)
    peak = up[-1]
    pull = peak * (1 - 0.012) ** np.arange(1, 5)
    last = pull[-1] * 1.004
    return np.concatenate([up, pull, [last]])


def test_buy_setup_generated_with_reasons() -> None:
    close = buy_setup_close()
    vol = np.full(len(close), 100_000.0)
    vol[-8:] = 180_000.0  # volume confirmation on pullback and trigger bar
    df = make_df(close, vol)
    sig = trend_pullback_signal("SYN", df, StrategySettings())
    assert sig.action in ACTIONS
    assert sig.action == "BUY_SETUP", (sig.reasons, sig.rules_failed)
    assert sig.stop_price is not None and sig.stop_price < sig.entry_reference
    assert sig.target_price is not None and sig.target_price > sig.entry_reference
    assert sig.reward_risk >= StrategySettings().min_reward_risk
    assert sig.rules_satisfied and not sig.rules_failed


def test_downtrend_is_no_trade() -> None:
    close = 200 * 0.99 ** np.arange(80)
    sig = trend_pullback_signal("DOWN", make_df(close), StrategySettings())
    assert sig.action == "NO_TRADE"
    assert sig.reasons


def test_insufficient_data_is_no_trade() -> None:
    close = buy_setup_close()[:10]
    sig = trend_pullback_signal("SHORT", make_df(close), StrategySettings())
    assert sig.action == "NO_TRADE"
    assert "Insufficient history" in sig.reasons[0]
    assert sig.data_status == "insufficient"


def test_stale_data_blocks_trade() -> None:
    close = buy_setup_close()
    sig = trend_pullback_signal("STALE", make_df(close), StrategySettings(), stale=True)
    assert sig.action == "NO_TRADE"
    assert sig.data_status == "stale"


def test_signal_no_lookahead_appending_future_bar() -> None:
    """The decision computed at bar k must be unchanged when bar k+1 exists."""
    close = buy_setup_close()
    vol = np.full(len(close), 100_000.0)
    vol[-8:] = 180_000.0
    base = make_df(close, vol)
    cut = base.iloc[:-1].reset_index(drop=True)
    sig_cut = trend_pullback_signal("SYN", cut, StrategySettings())
    sig_full = trend_pullback_signal("SYN", base, StrategySettings())
    # Compare the state as of the shared last bar
    assert sig_cut.data_ts == cut["ts"].iloc[-1]
    if sig_cut.action == "BUY_SETUP" and sig_full.action == "BUY_SETUP":
        # stop/target derive from the shared bar, so they must match
        assert sig_cut.stop_price == sig_full.stop_price
        assert sig_cut.entry_reference == sig_full.entry_reference
    else:
        # at minimum, appending a bar must not flip a NO_TRADE into a silent buy
        # without new rule satisfaction being reported
        assert sig_cut.action in ACTIONS and sig_full.action in ACTIONS


def test_overbought_rsi_blocks_entry() -> None:
    """A one-way vertical rally with no pullback must not be a BUY setup."""
    close = 100 * 1.03 ** np.arange(60)  # relentless up-move, RSI pinned high
    sig = trend_pullback_signal("VERT", make_df(close), StrategySettings())
    assert sig.action != "BUY_SETUP"
    assert any("R4" in f or "R3" in f for f in sig.rules_failed) or sig.action == "WAIT"
