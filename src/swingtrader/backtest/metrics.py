"""Backtest performance metrics. All definitions documented in docs/BACKTESTING.md."""

from __future__ import annotations

import math


def max_drawdown_pct(equity: list[float]) -> float:
    """Largest peak-to-trough decline of the equity curve (percent, >= 0)."""
    if not equity:
        return 0.0
    peak = -math.inf
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 4)


def compute_metrics(
    trades: list[dict],
    equity_curve: list[float],
    *,
    initial_capital: float,
    benchmark_return_pct: float,
) -> dict:
    """Aggregate trade/equity statistics. A zero-trade run is NOT success."""
    n = len(trades)
    gross = sum(t["pnl"] for t in trades)
    costs = sum(t["costs"] for t in trades)
    net = gross  # pnl entries are already net of costs
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (
        math.inf if gross_profit > 0 else 0.0
    )
    final_equity = equity_curve[-1] if equity_curve else initial_capital
    net_return_pct = 100 * (final_equity - initial_capital) / initial_capital
    hold_days = [t.get("holding_days", 0) for t in trades]
    exposure_pct = 100.0 if trades else 0.0  # refined below if curve provided
    turnover = sum(t["notional"] for t in trades)

    streak = 0
    worst_streak = 0
    for t in trades:
        if t["pnl"] <= 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0

    return {
        "status": "ok" if n > 0 else "no_trades",
        "trade_count": n,
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net, 2),
        "total_costs": round(costs, 2),
        "net_return_pct": round(net_return_pct, 4),
        "benchmark_return_pct": round(benchmark_return_pct, 4),
        "excess_return_pct": round(net_return_pct - benchmark_return_pct, 4),
        "win_rate_pct": round(100 * len(wins) / n, 2) if n else 0.0,
        "avg_winning_trade": round(avg_win, 2),
        "avg_losing_trade": round(avg_loss, 2),
        "profit_factor": profit_factor if profit_factor != math.inf else "inf",
        "max_drawdown_pct": max_drawdown_pct(equity_curve),
        "avg_holding_days": round(sum(hold_days) / n, 2) if n else 0.0,
        "turnover_inr": round(turnover, 2),
        "worst_loss_streak": worst_streak,
        "exposure_pct_estimate": exposure_pct,
    }
