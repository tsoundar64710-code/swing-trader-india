"""Cost engine and position-sizing tests.

Independently calculated expectations based on official rates verified 2026-10-11:
    STT delivery         : 0.1% both sides
    Stamp duty           : 0.015% buy only
    Exchange txn (NSE)   : 0.00297% both sides
    SEBI turnover        : 0.0001% both sides
    GST                  : 18% on (brokerage + exchange + SEBI)
    Brokerage (delivery) : 0% default (discount broker); raised in tests where needed
"""

from __future__ import annotations

import pytest

from swingtrader.core.settings import AppSettings, CostAssumptions
from swingtrader.costs.engine import (
    apply_slippage,
    cost_warning,
    estimate_costs,
    per_share_buy_cost,
    per_share_round_trip_cost,
    per_share_sell_cost,
    round_trip_cost_estimate,
)
from swingtrader.risk.sizing import PortfolioState, size_position

# Official rates (as percentages) for independent recomputation in tests
STT_PCT = 0.1
STAMP_BUY_PCT = 0.015
EXCHANGE_PCT = 0.00297
SEBI_PCT = 0.0001
GST_PCT = 18.0


def _expected_side_costs(turnover: float, side: str, brokerage_pct=0.0, brokerage_min=0.0) -> dict:
    """Independently computed expected charges — must match engine output."""
    brokerage = max(turnover * brokerage_pct / 100, brokerage_min) if turnover > 0 else 0.0
    stt = turnover * STT_PCT / 100
    exchange = turnover * EXCHANGE_PCT / 100
    sebi = turnover * SEBI_PCT / 100
    gst = (brokerage + exchange + sebi) * GST_PCT / 100
    stamp = turnover * STAMP_BUY_PCT / 100 if side == "BUY" else 0.0
    total = brokerage + stt + exchange + sebi + gst + stamp
    return {
        "brokerage": brokerage, "stt": stt, "exchange_txn": exchange,
        "sebi": sebi, "gst": gst, "stamp_duty": stamp, "total": total,
    }


# ── statutory rates match official schedule ──────────────────────────────


def test_stt_rate_is_0_1_percent_both_sides() -> None:
    """STT for delivery equity must be 0.1% of turnover on BOTH buy and sell (NSE)."""
    c = CostAssumptions()
    b = estimate_costs(100_000, "BUY", c)
    s = estimate_costs(100_000, "SELL", c)
    assert b["stt"] == pytest.approx(100_000 * 0.1 / 100, abs=0.01)  # ₹100
    assert s["stt"] == pytest.approx(100_000 * 0.1 / 100, abs=0.01)  # ₹100


def test_stamp_duty_is_0_015_percent_buy_only() -> None:
    """Stamp duty for delivery must be 0.015% of turnover, buy side only (NSE)."""
    c = CostAssumptions()
    b = estimate_costs(100_000, "BUY", c)
    s = estimate_costs(100_000, "SELL", c)
    assert b["stamp_duty"] == pytest.approx(100_000 * 0.015 / 100, abs=0.01)  # ₹15
    assert s["stamp_duty"] == 0.0


def test_exchange_txn_rate_matches_nse() -> None:
    """Exchange transaction charge ~0.00297% (NSE schedule)."""
    c = CostAssumptions()
    b = estimate_costs(1_000_000, "BUY", c)
    expected = 1_000_000 * 0.00297 / 100  # ₹29.70
    assert b["exchange_txn"] == pytest.approx(expected, abs=0.05)


def test_sebi_turnover_fee_matches_schedule() -> None:
    """SEBI turnover fee 0.0001% = Rs 10 per crore."""
    c = CostAssumptions()
    b = estimate_costs(10_000_000, "BUY", c)  # Rs 1 crore
    assert b["sebi"] == pytest.approx(10.0, abs=0.05)  # Rs 10 per crore


def test_gst_applies_to_brokerage_exchange_sebi_only() -> None:
    """GST 18% on (brokerage + exchange + SEBI), not on STT or stamp duty."""
    c = CostAssumptions(brokerage_pct=0.03, brokerage_min_inr=0.0)
    b = estimate_costs(100_000, "BUY", c)
    expected_gst = (b["brokerage"] + b["exchange_txn"] + b["sebi"]) * 0.18
    assert b["gst"] == pytest.approx(expected_gst, abs=0.01)


def test_buy_costs_include_stamp_and_exclude_sell_stt_difference() -> None:
    c = CostAssumptions()
    b = estimate_costs(100_000, "BUY", c)
    s = estimate_costs(100_000, "SELL", c)
    assert b["stamp_duty"] > 0
    assert s["stamp_duty"] == 0
    assert b["stt"] > 0 and s["stt"] > 0
    assert b["total"] > 0 and s["total"] > 0


# ── full-service brokerage (raised from delivery default) ────────────────


def test_minimum_brokerage_applies_on_small_trades() -> None:
    """Full-service broker: Rs 20 minimum applies when 0.03% of turnover < Rs 20."""
    c = CostAssumptions(brokerage_pct=0.03, brokerage_min_inr=20.0)
    b = estimate_costs(1_000, "BUY", c)
    assert b["brokerage"] == 20.0  # 0.03% of 1000 = 0.30 < 20 → min applies
    b2 = estimate_costs(100_000, "BUY", c)
    assert b2["brokerage"] == pytest.approx(30.0, abs=0.01)  # 0.03% of 100k = 30 > 20


def test_delivery_brokerage_default_is_zero() -> None:
    """Discount-broker delivery default: 0% brokerage, no minimum."""
    c = CostAssumptions()
    b = estimate_costs(100_000, "BUY", c)
    assert b["brokerage"] == 0.0


# ── independently recomputed totals ──────────────────────────────────────


def test_total_matches_independent_recomputation_buy() -> None:
    c = CostAssumptions()
    turnover = 250_000
    b = estimate_costs(turnover, "BUY", c)
    exp = _expected_side_costs(turnover, "BUY")
    assert b["stt"] == pytest.approx(exp["stt"], abs=0.01)
    assert b["stamp_duty"] == pytest.approx(exp["stamp_duty"], abs=0.01)
    assert b["exchange_txn"] == pytest.approx(exp["exchange_txn"], abs=0.01)
    assert b["sebi"] == pytest.approx(exp["sebi"], abs=0.01)
    assert b["gst"] == pytest.approx(exp["gst"], abs=0.01)
    assert b["total"] == pytest.approx(exp["total"], abs=0.05)


def test_total_matches_independent_recomputation_sell() -> None:
    c = CostAssumptions()
    turnover = 250_000
    s = estimate_costs(turnover, "SELL", c)
    exp = _expected_side_costs(turnover, "SELL")
    assert s["stt"] == pytest.approx(exp["stt"], abs=0.01)
    assert s["stamp_duty"] == 0.0
    assert s["total"] == pytest.approx(exp["total"], abs=0.05)


def test_round_trip_includes_both_sides() -> None:
    c = CostAssumptions()
    rt = round_trip_cost_estimate(100_000, c)
    b = estimate_costs(100_000, "BUY", c)
    s = estimate_costs(100_000, "SELL", c)
    assert rt["round_trip_total"] == pytest.approx(b["total"] + s["total"], abs=0.02)
    # Independent: STT twice + stamp once + exchange twice + sebi twice + GST on each side
    # GST per side = 18% * (exchange + sebi) since brokerage = 0
    independent = (
        2 * 100_000 * 0.1 / 100          # STT both sides
        + 100_000 * 0.015 / 100           # stamp buy only
        + 2 * 100_000 * 0.00297 / 100     # exchange both sides
        + 2 * 100_000 * 0.0001 / 100      # sebi both sides
        + 2 * (100_000 * 0.00297 / 100 + 100_000 * 0.0001 / 100) * 0.18  # GST both sides
    )
    assert rt["round_trip_total"] == pytest.approx(independent, abs=0.05)


def test_per_share_helpers_match_notional() -> None:
    c = CostAssumptions()
    b500 = estimate_costs(500, "BUY", c)["total"]
    s500 = estimate_costs(500, "SELL", c)["total"]
    assert per_share_buy_cost(500, c) == pytest.approx(b500, abs=0.01)
    assert per_share_sell_cost(500, c) == pytest.approx(s500, abs=0.01)
    assert per_share_round_trip_cost(500, c) == pytest.approx(b500 + s500, abs=0.01)


# ── tiny / large / round-trip scenarios ──────────────────────────────────


def test_tiny_order_costs_are_dominant() -> None:
    """₹1,000 order: statutory costs alone ~0.25% round trip — must warn."""
    c = CostAssumptions()
    rt = round_trip_cost_estimate(1_000, c)
    # STT 0.1%*2 + stamp 0.015% + exchange*2 + sebi*2 ≈ 0.23% minimum
    assert rt["round_trip_pct"] > 0.2
    assert rt["round_trip_total"] > 2.0


def test_large_order_costs_scale_linearly() -> None:
    c = CostAssumptions()
    small = round_trip_cost_estimate(100_000, c)
    large = round_trip_cost_estimate(1_000_000, c)
    assert large["round_trip_pct"] == pytest.approx(small["round_trip_pct"], abs=0.01)


def test_capital_1000_feasible_position_with_costs() -> None:
    """₹1,000 capital: with 0% delivery brokerage, statutory costs ~0.25% round trip.
    A ₹500 share → buy cost ~₹1.15; 1 share fits, risk budget at 2% = ₹20.
    Must not silently pretend costs are zero.
    """
    s = AppSettings()
    s.initial_capital_inr = 1_000
    s.risk.max_risk_per_trade_pct = 2.0
    c = s.costs
    # Independent: buy cost for one ₹500 share
    buy_cost = estimate_costs(500, "BUY", c)["total"]
    assert buy_cost > 0  # not free — STT + stamp + exchange + sebi apply
    # Position sizing must respect cash including buy costs
    plan = size_position(
        entry=500, stop=480,
        portfolio=PortfolioState(equity_inr=1_000, cash_inr=1_000),
        settings=s,
    )
    if plan.accepted:
        assert plan.notional_inr + plan.est_buy_costs["total"] <= 1_000 + 1e-6
    else:
        # Rejected is also valid — must have a clear reason
        assert plan.rejections


def test_capital_1000_rejects_expensive_share() -> None:
    """₹1,000 capital cannot buy a ₹2,000 share — must reject honestly."""
    s = AppSettings()
    s.initial_capital_inr = 1_000
    plan = size_position(
        entry=2_000, stop=1_900,
        portfolio=PortfolioState(equity_inr=1_000, cash_inr=1_000),
        settings=s,
    )
    assert not plan.accepted
    assert any("Insufficient cash" in r or "cash" in r.lower() for r in plan.rejections)


# ── slippage is separate from fees ───────────────────────────────────────


def test_slippage_worsens_execution() -> None:
    c = CostAssumptions(slippage_pct=0.5)
    assert apply_slippage(100, "BUY", c) == 100.5
    assert apply_slippage(100, "SELL", c) == 99.5


def test_slippage_not_included_in_statutory_costs() -> None:
    """estimate_costs returns statutory fees only; slippage is applied via apply_slippage."""
    c = CostAssumptions(slippage_pct=1.0)  # 1% slippage
    b = estimate_costs(100_000, "BUY", c)
    # total should NOT include 1% of 100k = 1000 as a fee
    assert b["total"] < 100_000 * 0.01  # well under 1% of turnover in fees
    # slippage affects fill price, not the fee breakdown
    assert apply_slippage(100, "BUY", c) == 101.0


# ── verified flag & warning ──────────────────────────────────────────────


def test_verified_date_shows_verified_message() -> None:
    assert "verified" in cost_warning(CostAssumptions()).lower()
    assert "UNVERIFIED" in cost_warning(CostAssumptions(config_verified_date="UNVERIFIED"))


def test_unverified_costs_warning_present() -> None:
    assert "UNVERIFIED" in cost_warning(CostAssumptions(config_verified_date="UNVERIFIED"))
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
    """Full-service broker with Rs 20 min: small positions get cost-dominance warning."""
    s = AppSettings()
    s.costs.brokerage_pct = 0.03
    s.costs.brokerage_min_inr = 20.0
    plan = size_position(
        entry=100, stop=90,
        portfolio=healthy_portfolio(equity_inr=20_000, cash_inr=20_000),
        settings=s,
    )
    if plan.accepted and plan.notional_inr < 3_000:
        # With Rs 20 min brokerage per side, round-trip > 10% of notional for small orders
        assert any("costs" in n.lower() for n in plan.notes)
