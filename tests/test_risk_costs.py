"""Cost engine and position-sizing tests."""

from __future__ import annotations

import pytest

from swingtrader.core.settings import AppSettings, CostAssumptions
from swingtrader.costs.engine import (
    apply_slippage,
    cost_warning,
    estimate_costs,
    round_trip_cost_estimate,
)
from swingtrader.risk.sizing import PortfolioState, size_position


def test_buy_costs_include_stamp_and_exclude_sell_stt_difference() -> None:
    c = CostAssumptions()
    b = estimate_costs(100_000, "BUY", c)
    s = estimate_costs(100_000, "SELL", c)
    assert b["stamp_duty"] > 0
    assert s["stamp_duty"] == 0
    assert b["stt"] > 0 and s["stt"] > 0
    assert b["total"] > 0 and s["total"] > 0
    assert b["gst"] == pytest.approx(
        (b["brokerage"] + b["exchange_txn"] + b["sebi"]) * 0.18, abs=0.01
    )


def test_minimum_brokerage_applies_on_small_trades() -> None:
    c = CostAssumptions()
    b = estimate_costs(1_000, "BUY", c)
    assert b["brokerage"] == c.brokerage_min_inr  # 0.03% of 1000 = 0.30 < 20


def test_slippage_worsens_execution() -> None:
    c = CostAssumptions(slippage_pct=0.5)
    assert apply_slippage(100, "BUY", c) == 100.5
    assert apply_slippage(100, "SELL", c) == 99.5


def test_unverified_costs_warning_present() -> None:
    assert "UNVERIFIED" in cost_warning(CostAssumptions())
    assert "2026-10-11" in cost_warning(CostAssumptions(config_verified_date="2026-10-11"))


def test_round_trip_pct() -> None:
    rt = round_trip_cost_estimate(100_000, CostAssumptions())
    assert rt["round_trip_total"] == pytest.approx(rt["buy_total"] + rt["sell_total"], abs=0.02)
    assert rt["round_trip_pct"] == pytest.approx(
        round(100 * rt["round_trip_total"] / 100_000, 4), abs=1e-9
    )


# ------------------------------------------------------------- sizing


def healthy_portfolio(**kw) -> PortfolioState:
    base = dict(equity_inr=100_000, cash_inr=100_000, open_positions=0, exposure_inr=0.0)
    base.update(kw)
    return PortfolioState(**base)


def test_sizing_basic_whole_shares() -> None:
    s = AppSettings()
    plan = size_position(entry=500, stop=480, portfolio=healthy_portfolio(), settings=s)
    assert plan.accepted
    assert plan.qty >= 1
    assert float(plan.qty).is_integer()
    risk_budget = 100_000 * s.risk.max_risk_per_trade_pct / 100
    assert plan.est_total_risk_inr <= risk_budget + 1e-6


def test_sizing_rejects_invalid_stop() -> None:
    plan = size_position(100, 110, healthy_portfolio(), AppSettings())
    assert not plan.accepted
    assert any("Invalid stop" in r for r in plan.rejections)


def test_sizing_rejects_insufficient_cash() -> None:
    s = AppSettings()
    plan = size_position(
        entry=1_000, stop=950,
        portfolio=healthy_portfolio(equity_inr=500, cash_inr=500),
        settings=s,
    )
    assert not plan.accepted
    assert any("Insufficient cash" in r for r in plan.rejections)


def test_sizing_respects_max_position_pct() -> None:
    s = AppSettings()
    s.risk.max_position_pct = 10  # 10k of 100k equity
    plan = size_position(entry=100, stop=95, portfolio=healthy_portfolio(), settings=s)
    assert plan.accepted
    assert plan.notional_inr <= 100_000 * 0.10 + 1e-6


def test_sizing_blocks_when_max_positions_reached() -> None:
    s = AppSettings()
    s.risk.max_open_positions = 2
    plan = size_position(
        100, 95, healthy_portfolio(open_positions=2), settings=s
    )
    assert not plan.accepted
    assert any("Max open positions" in r for r in plan.rejections)


def test_sizing_blocks_on_portfolio_exposure_limit() -> None:
    s = AppSettings()
    s.risk.max_portfolio_exposure_pct = 20
    plan = size_position(
        100, 95,
        healthy_portfolio(exposure_inr=19_500),
        settings=s,
    )
    assert not plan.accepted
    assert any("exposure limit" in r.lower() for r in plan.rejections)


def test_sizing_blocks_on_daily_loss_limit() -> None:
    s = AppSettings()
    plan = size_position(
        100, 95,
        healthy_portfolio(realized_pnl_today_inr=-3_500),  # > 3% of 100k
        settings=s,
    )
    assert not plan.accepted
    assert any("Daily" in r for r in plan.rejections)


def test_sizing_blocks_when_trading_disabled() -> None:
    plan = size_position(
        100, 95, healthy_portfolio(trading_disabled=True), settings=AppSettings()
    )
    assert not plan.accepted
    assert any("disabled" in r.lower() for r in plan.rejections)


def test_tiny_capital_flags_cost_dominance() -> None:
    """₹1,000-scale capital: costs dominate — must warn, not force a trade."""
    s = AppSettings()
    s.initial_capital_inr = 1_000
    s.risk.max_risk_per_trade_pct = 2.0
    plan = size_position(
        entry=2_000, stop=1_900,
        portfolio=healthy_portfolio(equity_inr=1_000, cash_inr=1_000),
        settings=s,
    )
    # A ₹2,000 share can't be bought with ₹1,000 — must reject honestly
    assert not plan.accepted
    assert plan.rejections


def test_small_position_cost_warning_shown() -> None:
    s = AppSettings()
    plan = size_position(
        entry=100, stop=90,
        portfolio=healthy_portfolio(equity_inr=20_000, cash_inr=20_000),
        settings=s,
    )
    if plan.accepted and plan.notional_inr < 3_000:
        assert any("costs" in n.lower() for n in plan.notes)
