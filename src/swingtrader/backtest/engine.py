"""Deterministic backtest engine (long-only, daily bars, one instrument).

Timing model (documented, conservative):
  - Signals are evaluated on the CLOSE of bar i using only data <= i.
  - Entries execute at the OPEN of bar i+1 with adverse slippage.
  - Stops execute at the stop price, or at the next open when the bar gaps
    through the stop (worse fill).
  - Targets execute at the target price if touched (stop takes priority when
    both are hit in the same bar — conservative).
  - Costs are charged on both sides using the configured cost model.

Indicators are precomputed once; every indicator value is causal (uses only
past rows), which is regression-tested in tests/test_backtest.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from swingtrader.backtest.metrics import compute_metrics
from swingtrader.core.settings import AppSettings
from swingtrader.costs.engine import apply_slippage, estimate_costs
from swingtrader.strategies.indicators import add_indicators
from swingtrader.strategies.signals import evaluate_trend_pullback


@dataclass
class BacktestResult:
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)


def _exit_costs(price: float, qty: int, settings: AppSettings) -> dict:
    return estimate_costs(price * qty, "SELL", settings.costs)


def _entry_costs(price: float, qty: int, settings: AppSettings) -> dict:
    return estimate_costs(price * qty, "BUY", settings.costs)


def run_backtest(
    df: pd.DataFrame,
    settings: AppSettings,
    *,
    initial_capital: float | None = None,
    max_holding_bars: int = 15,
    symbol: str = "SYMBOL",
) -> BacktestResult:
    """Run a single-instrument long-only backtest over `df` (chronological)."""
    res = BacktestResult()
    capital0 = float(initial_capital or settings.initial_capital_inr)
    res.config = {
        "symbol": symbol,
        "initial_capital": capital0,
        "max_holding_bars": max_holding_bars,
        "strategy": "trend_pullback_v1",
        "params": settings.strategy.model_dump(),
        "costs": settings.costs.model_dump(),
        "timing": "signal@close(i) -> entry@open(i+1) with slippage; stop priority over target",
    }
    if df is None or len(df) < settings.strategy.sma_slow + 5:
        res.warnings.append("Insufficient bars for the configured strategy warm-up.")
        res.metrics = compute_metrics(
            [], [], initial_capital=capital0, benchmark_return_pct=0.0
        )
        res.metrics["status"] = "insufficient_data"
        return res

    ind = add_indicators(df, settings.strategy)
    cash = capital0
    pos_qty = 0
    entry_price = 0.0
    stop = 0.0
    target = 0.0
    entry_idx = -1
    entry_costs_total = 0.0
    pending_entry = False

    # Benchmark: buy & hold from first open to last close (no costs — documented)
    b_first_open = float(ind["open"].iloc[0])
    b_last_close = float(ind["close"].iloc[-1])
    benchmark_return_pct = 100.0 * (b_last_close - b_first_open) / b_first_open

    n = len(ind)
    for i in range(n - 1):
        row = ind.iloc[i]
        nxt = ind.iloc[i + 1]
        equity = cash + (pos_qty * float(row["close"]) if pos_qty else 0.0)
        res.equity_curve.append(round(equity, 2))
        res.dates.append(str(row["ts"]))

        # ---- manage open position on bar i+1's price path ----
        if pos_qty > 0:
            o, h, lo, c = (float(nxt[k]) for k in ("open", "high", "low", "close"))
            exit_price = None
            reason = None
            if lo <= stop:
                exit_price = o if o < stop else stop  # gap model
                reason = "stop" if o >= stop else "stop_gap"
            elif h >= target:
                exit_price = target
                reason = "target"
            elif i + 1 - entry_idx >= max_holding_bars:
                exit_price = apply_slippage(c, "SELL", settings.costs)
                reason = "time_exit"
            elif pd.notna(nxt["sma_slow"]) and c < float(nxt["sma_slow"]):
                exit_price = apply_slippage(c, "SELL", settings.costs)
                reason = "invalidation"

            if exit_price is not None:
                sell_costs = _exit_costs(exit_price, pos_qty, settings)
                proceeds = pos_qty * exit_price - sell_costs["total"]
                cash += proceeds
                pnl = proceeds - (entry_price * pos_qty + entry_costs_total)
                res.trades.append(
                    {
                        "symbol": symbol,
                        "entry_ts": (
                            res.dates[entry_idx]
                            if 0 <= entry_idx < len(res.dates)
                            else str(ind["ts"].iloc[entry_idx])
                        ),
                        "entry_price": round(entry_price, 2),
                        "exit_ts": str(nxt["ts"]),
                        "exit_price": round(exit_price, 2),
                        "qty": pos_qty,
                        "costs": round(entry_costs_total + sell_costs["total"], 2),
                        "pnl": round(pnl, 2),
                        "notional": round(entry_price * pos_qty, 2),
                        "holding_days": i + 1 - entry_idx,
                        "exit_reason": reason,
                    }
                )
                pos_qty = 0
                pending_entry = False

        # ---- evaluate setup at close of i+1, execute at open of i+2 ----
        if pos_qty == 0:
            window = ind.iloc[: i + 2]
            sig = evaluate_trend_pullback(symbol, window, settings.strategy)
            if sig.action == "BUY_SETUP" and i + 2 < n:
                pending_entry = True
                pending_stop = float(sig.stop_price)
                pending_target = float(sig.target_price)

        if pending_entry and pos_qty == 0 and i + 2 < n:
            # execute at open of bar i+2 (the bar after the signal bar)
            exec_bar = i + 2
            fill = apply_slippage(float(ind["open"].iloc[exec_bar]), "BUY", settings.costs)
            risk_per_share = fill - pending_stop
            risk_budget = cash * settings.risk.max_risk_per_trade_pct / 100
            # conservative whole-share sizing under risk budget + cash
            buy1 = estimate_costs(fill, "BUY", settings.costs)
            sell1 = estimate_costs(fill, "SELL", settings.costs)
            denom = risk_per_share + buy1["total"] + sell1["total"]
            qty_by_risk = int(math.floor(risk_budget / denom)) if denom > 0 else 0
            per_share_buy = fill + buy1["total"]
            qty_by_cash = int(math.floor(cash / per_share_buy)) if per_share_buy > 0 else 0
            qty = min(qty_by_risk, qty_by_cash)
            if qty >= 1 and risk_per_share > 0:
                costs_e = estimate_costs(fill * qty, "BUY", settings.costs)
                if fill * qty + costs_e["total"] <= cash + 1e-6:
                    cash -= fill * qty + costs_e["total"]
                    pos_qty = qty
                    entry_price = fill
                    entry_costs_total = costs_e["total"]
                    entry_idx = exec_bar
                    stop = pending_stop
                    target = pending_target
            pending_entry = False

    # close final bar mark-to-market
    if ind is not None and len(ind):
        last_eq = cash + (pos_qty * float(ind["close"].iloc[-1]) if pos_qty else 0.0)
        res.equity_curve.append(round(last_eq, 2))
        res.dates.append(str(ind["ts"].iloc[-1]))
        if pos_qty > 0:
            res.warnings.append(
                "Position still open at the end of the sample; marked to market at the "
                "last close (not closed)."
            )

    res.metrics = compute_metrics(
        res.trades,
        res.equity_curve,
        initial_capital=capital0,
        benchmark_return_pct=benchmark_return_pct,
    )
    res.metrics["gross_return_pct_before_costs_reference"] = benchmark_return_pct
    if res.metrics["trade_count"] == 0:
        res.warnings.append(
            "No trades were generated. This is NOT a successful result — the sample, "
            "parameters, or costs may simply not produce setups."
        )
    res.warnings.append(
        "Backtests are hindsight simulations. Past results never guarantee future "
        "returns. Overfitting, regime change and survivorship bias apply."
    )
    return res


def chronological_split(n: int, train: float = 0.6, val: float = 0.2) -> dict[str, tuple[int, int]]:
    """Row-contiguous, non-overlapping splits (no shuffling)."""
    if train <= 0 or val < 0 or train + val >= 1.0:
        raise ValueError("Invalid split fractions")
    a = int(n * train)
    b = int(n * (train + val))
    return {"train": (0, a), "validation": (a, b), "test": (b, n)}


def run_split_backtest(
    df: pd.DataFrame,
    settings: AppSettings,
    *,
    train: float = 0.6,
    val: float = 0.2,
    initial_capital: float | None = None,
) -> dict[str, BacktestResult]:
    """Run independent backtests per chronological split (fresh capital each)."""
    bounds = chronological_split(len(df), train, val)
    out: dict[str, BacktestResult] = {}
    for name, (a, b) in bounds.items():
        chunk = df.iloc[a:b].reset_index(drop=True)
        r = run_backtest(chunk, settings, initial_capital=initial_capital)
        r.config["split"] = name
        r.config["split_range"] = (a, b)
        out[name] = r
    return out


def run_walk_forward(
    df: pd.DataFrame,
    settings: AppSettings,
    *,
    train_bars: int = 250,
    test_bars: int = 60,
    initial_capital: float | None = None,
) -> BacktestResult:
    """Anchored walk-forward: expand training window, trade only on the next block."""
    combined = BacktestResult(config={"mode": "walk_forward", "train_bars": train_bars,
                                      "test_bars": test_bars})
    start = train_bars
    if len(df) <= start:
        combined.metrics = {"status": "insufficient_data"}
        combined.warnings.append("Not enough bars for walk-forward.")
        return combined
    capital = float(initial_capital or settings.initial_capital_inr)
    while start + test_bars <= len(df):
        test_chunk = df.iloc[start : start + test_bars].reset_index(drop=True)
        r = run_backtest(test_chunk, settings, initial_capital=capital)
        combined.trades.extend(r.trades)
        if r.equity_curve:
            capital = r.equity_curve[-1]
        combined.equity_curve.extend(r.equity_curve)
        combined.dates.extend(r.dates)
        start += test_bars
    combined.metrics = compute_metrics(
        combined.trades, combined.equity_curve,
        initial_capital=float(initial_capital or settings.initial_capital_inr),
        benchmark_return_pct=0.0,
    )
    combined.warnings.append(
        "Walk-forward: parameters were NOT re-optimized per window (fixed config). "
        "This reduces — but does not eliminate — overfitting risk."
    )
    return combined
