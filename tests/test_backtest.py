"""Backtest engine tests. All fixtures are SYNTHETIC price paths."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swingtrader.backtest.engine import (
    chronological_split,
    run_backtest,
    run_split_backtest,
    run_walk_forward,
)
from swingtrader.core.settings import AppSettings, CostAssumptions, RiskLimits


def make_df(
    close: np.ndarray, volume: np.ndarray | None = None, opens: np.ndarray | None = None,
    start: str = "2025-01-01",
) -> pd.DataFrame:
    n = len(close)
    dates = pd.bdate_range(start, periods=n)
    open_ = close * 1.001 if opens is None else opens
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    vol = np.full(n, 100_000.0) if volume is None else volume.astype(float)
    return pd.DataFrame(
        {
            "ts": [d.strftime("%Y-%m-%d") for d in dates],
            "open": open_, "high": high, "low": low, "close": close, "volume": vol,
        }
    )


def cycle_data(cycles: int = 2) -> pd.DataFrame:
    """SYNTHETIC: repeated uptrend + pullback + bounce cycles."""
    parts = []
    price = 100.0
    for _ in range(cycles):
        up = price * 1.01 ** np.arange(55)
        price = up[-1]
        pull = price * (1 - 0.012) ** np.arange(1, 5)
        price = pull[-1]
        bounce = [price * 1.005]
        price = bounce[0]
        parts.append(np.concatenate([up, pull, bounce]))
    close = np.concatenate(parts)
    vol = np.full(len(close), 100_000.0)
    # raise volume around each cycle end
    for c in range(cycles):
        end = 55 + c * 61
        vol[max(0, end - 10): end + 1] = 200_000.0
    return make_df(close, vol)


def free_cost_settings() -> AppSettings:
    s = AppSettings()
    s.costs = CostAssumptions(
        brokerage_pct=0.0, brokerage_min_inr=0.0, stt_buy_pct=0.0, stt_sell_pct=0.0,
        exchange_txn_charge_pct=0.0, gst_pct=0.0, sebi_charge_pct=0.0,
        stamp_duty_buy_pct=0.0, slippage_pct=0.0,
    )
    return s


def test_split_non_overlapping_and_complete() -> None:
    b = chronological_split(100, 0.6, 0.2)
    assert b["train"] == (0, 60)
    assert b["validation"] == (60, 80)
    assert b["test"] == (80, 100)


def test_insufficient_data_reported_as_not_success() -> None:
    df = make_df(np.linspace(100, 110, 10))
    res = run_backtest(df, AppSettings())
    assert res.metrics["status"] == "insufficient_data"
    assert res.metrics["trade_count"] == 0


def test_no_trades_is_not_success() -> None:
    close = 200 * 0.99 ** np.arange(120)
    res = run_backtest(make_df(close), AppSettings())
    assert res.metrics["trade_count"] == 0
    assert res.metrics["status"] == "no_trades"
    assert any("NOT a successful result" in w for w in res.warnings)


def test_produces_trades_and_respects_accounting() -> None:
    res = run_backtest(cycle_data(2), AppSettings())
    assert res.metrics["trade_count"] >= 1
    for t in res.trades:
        assert t["qty"] >= 1
        assert t["exit_price"] > 0
        assert t["costs"] > 0  # default cost model charges something
    assert len(res.equity_curve) == len(res.dates)


def test_costs_reduce_net_pnl() -> None:
    df = cycle_data(2)
    with_costs = run_backtest(df, AppSettings())
    free = run_backtest(df, free_cost_settings())
    if with_costs.trades and free.trades:
        assert with_costs.metrics["net_pnl"] <= free.metrics["net_pnl"]


def test_prefix_run_matches_full_run_for_contained_trades() -> None:
    """No look-ahead: trades fully inside a prefix must be identical."""
    df = cycle_data(2)
    k = 90  # cut before second cycle completes
    full = run_backtest(df, AppSettings())
    prefix = run_backtest(df.iloc[:k].reset_index(drop=True), AppSettings())
    cut_ts = str(df["ts"].iloc[k - 1])
    full_contained = [t for t in full.trades if t["exit_ts"] <= cut_ts]
    assert len(prefix.trades) == len(full_contained)
    for a, b in zip(prefix.trades, full_contained, strict=True):
        assert a["entry_ts"] == b["entry_ts"]
        assert a["exit_ts"] == b["exit_ts"]
        assert a["entry_price"] == b["entry_price"]
        assert a["exit_price"] == b["exit_price"]
        assert a["qty"] == b["qty"]
        assert a["pnl"] == b["pnl"]


def test_stop_gap_fills_at_worse_open() -> None:
    """A bar that opens far below the stop must fill at the open (worse)."""
    df = cycle_data(1)
    last_ts = pd.Timestamp(df["ts"].iloc[-1])
    # bar A: normal session (entry executes at its open), bar B: gaps far below stop
    normal_open = float(df["close"].iloc[-1]) * 1.001
    crash_open = normal_open * 0.85
    extra = pd.DataFrame(
        {
            "ts": [
                pd.bdate_range(last_ts + pd.Timedelta(days=1), periods=2)[i].strftime("%Y-%m-%d")
                for i in range(2)
            ],
            "open": [normal_open, crash_open],
            "high": [normal_open * 1.01, crash_open * 1.001],
            "low": [normal_open * 0.99, crash_open * 0.99],
            "close": [normal_open * 1.005, crash_open * 0.995],
            "volume": [150_000.0, 500_000.0],
        }
    )
    ext = pd.concat([df, extra], ignore_index=True)
    res = run_backtest(ext, AppSettings())
    assert res.trades, "expected the crashing bar to close the position"
    t = res.trades[-1]
    assert t["exit_reason"] == "stop_gap"
    assert t["exit_price"] == pytest.approx(crash_open, abs=0.01)
    # loss must be worse than a planned stop exit
    assert t["pnl"] < 0


def test_split_backtest_runs_each_split() -> None:
    out = run_split_backtest(cycle_data(3), AppSettings())
    assert set(out) == {"train", "validation", "test"}
    for r in out.values():
        assert "status" in r.metrics


def test_walk_forward_runs() -> None:
    df = cycle_data(4)
    res = run_walk_forward(df, AppSettings(), train_bars=80, test_bars=30)
    assert res.metrics["status"] in ("ok", "no_trades")
    assert any("Walk-forward" in w for w in res.warnings)


def test_slippage_worsens_results() -> None:
    df = cycle_data(2)
    no_slip = free_cost_settings()
    slip = AppSettings()
    slip.costs = CostAssumptions(
        brokerage_pct=0.0, brokerage_min_inr=0.0, stt_buy_pct=0.0, stt_sell_pct=0.0,
        exchange_txn_charge_pct=0.0, gst_pct=0.0, sebi_charge_pct=0.0,
        stamp_duty_buy_pct=0.0, slippage_pct=0.5,
    )
    a = run_backtest(df, no_slip)
    b = run_backtest(df, slip)
    if a.trades and b.trades:
        assert b.metrics["net_pnl"] <= a.metrics["net_pnl"]


def test_risk_limit_gates_position_count() -> None:
    s = AppSettings()
    s.risk = RiskLimits(max_risk_per_trade_pct=0.2, max_position_pct=1.0)
    res = run_backtest(cycle_data(3), s)
    # tighter risk budget → smaller or fewer positions; never larger notional than limit
    for t in res.trades:
        assert t["notional"] <= s.initial_capital_inr * 0.01 + 1e-6
