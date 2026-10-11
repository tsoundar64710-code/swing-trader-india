"""Deterministic position sizing and portfolio risk checks.

Risk-per-share model (long):
    risk_per_share = entry_reference - stop_price
    estimated position risk = qty * risk_per_share + estimated round-trip costs

Quantity is the minimum of what the cash constraint and the risk budget allow,
rounded DOWN to whole shares, then re-checked against every limit including fees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from swingtrader.core.settings import AppSettings
from swingtrader.costs.engine import (
    estimate_costs,
    per_share_buy_cost,
    per_share_round_trip_cost,
    round_trip_cost_estimate,
)


@dataclass
class PositionPlan:
    accepted: bool
    qty: int = 0
    entry_reference: float = 0.0
    stop_price: float = 0.0
    risk_per_share: float = 0.0
    notional_inr: float = 0.0
    est_buy_costs: dict = field(default_factory=dict)
    est_round_trip_costs: dict = field(default_factory=dict)
    est_total_risk_inr: float = 0.0
    risk_budget_inr: float = 0.0
    rejections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "qty": self.qty,
            "entry_reference": self.entry_reference,
            "stop_price": self.stop_price,
            "risk_per_share": self.risk_per_share,
            "notional_inr": round(self.notional_inr, 2),
            "est_buy_costs": self.est_buy_costs,
            "est_round_trip_costs": self.est_round_trip_costs,
            "est_total_risk_inr": round(self.est_total_risk_inr, 2),
            "risk_budget_inr": round(self.risk_budget_inr, 2),
            "rejections": list(self.rejections),
            "notes": list(self.notes),
        }


@dataclass
class PortfolioState:
    equity_inr: float  # cash + market value of open positions
    cash_inr: float
    open_positions: int = 0
    exposure_inr: float = 0.0  # current invested capital
    realized_pnl_today_inr: float = 0.0
    peak_equity_inr: float | None = None
    trading_disabled: bool = False


def size_position(
    entry: float,
    stop: float,
    portfolio: PortfolioState,
    settings: AppSettings,
) -> PositionPlan:
    """Compute a whole-share position plan, enforcing every configured limit."""
    costs = settings.costs
    risk = settings.risk
    plan = PositionPlan(accepted=False, entry_reference=entry, stop_price=stop)

    if portfolio.trading_disabled:
        plan.rejections.append("Trading is globally disabled (emergency stop active).")
        return plan
    if entry <= 0:
        plan.rejections.append("Entry reference must be positive.")
        return plan
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        plan.rejections.append(
            f"Invalid stop: stop ({stop:.2f}) must be below entry ({entry:.2f})."
        )
        return plan
    plan.risk_per_share = round(risk_per_share, 4)

    equity = max(portfolio.equity_inr, 0.0)
    plan.risk_budget_inr = equity * risk.max_risk_per_trade_pct / 100

    # --- quantity by risk budget (costs included conservatively per share) ---
    per_share_rt_cost = per_share_round_trip_cost(entry, costs)
    qty_by_risk = int(math.floor(plan.risk_budget_inr / (risk_per_share + per_share_rt_cost)))

    # --- quantity by cash (buy cost per share incl. statutory charges, no slippage) ---
    per_share_buy = entry + per_share_buy_cost(entry, costs)
    qty_by_cash = int(math.floor(portfolio.cash_inr / per_share_buy)) if per_share_buy > 0 else 0

    # --- quantity by max position notional ---
    max_notional = equity * risk.max_position_pct / 100
    qty_by_notional = int(math.floor(max_notional / entry)) if entry > 0 else 0

    qty = min(qty_by_risk, qty_by_cash, qty_by_notional)
    if qty < 1:
        if qty_by_cash < 1:
            plan.rejections.append(
                f"Insufficient cash: ₹{portfolio.cash_inr:,.2f} cannot buy even 1 share "
                f"at ~₹{per_share_buy:,.2f} including buy costs."
            )
        if qty_by_risk < 1:
            plan.rejections.append(
                f"Risk budget ₹{plan.risk_budget_inr:,.2f} is smaller than the risk of one share "
                f"(₹{risk_per_share + per_share_rt_cost:,.2f} incl. costs)."
            )
        if qty_by_notional < 1:
            plan.rejections.append(
                f"Notional of 1 share (₹{entry:,.2f}) exceeds the per-position limit "
                f"₹{max_notional:,.2f}."
            )
        return plan

    plan.qty = qty
    plan.notional_inr = qty * entry
    plan.est_buy_costs = estimate_costs(plan.notional_inr, "BUY", costs)
    plan.est_round_trip_costs = round_trip_cost_estimate(plan.notional_inr, costs)
    plan.est_total_risk_inr = qty * risk_per_share + plan.est_round_trip_costs["round_trip_total"]

    # --- re-checks after fees ---
    if plan.notional_inr + plan.est_buy_costs["total"] > portfolio.cash_inr + 1e-6:
        plan.rejections.append("Order + buy costs exceed available cash after sizing.")
        return plan
    if plan.est_total_risk_inr > plan.risk_budget_inr + 1e-6:
        # shrink once more
        qty2 = int(
            math.floor(
                plan.risk_budget_inr
                / (risk_per_share + plan.est_round_trip_costs["round_trip_total"] / qty)
            )
        )
        if qty2 < 1:
            plan.rejections.append(
                "Risk budget cannot cover one share once estimated costs are included."
            )
            return plan
        plan.qty = qty2
        plan.notional_inr = qty2 * entry
        plan.est_buy_costs = estimate_costs(plan.notional_inr, "BUY", costs)
        plan.est_round_trip_costs = round_trip_cost_estimate(plan.notional_inr, costs)
        rt_total = plan.est_round_trip_costs["round_trip_total"]
        plan.est_total_risk_inr = qty2 * risk_per_share + rt_total

    if portfolio.open_positions + 1 > risk.max_open_positions:
        plan.rejections.append(
            f"Max open positions ({risk.max_open_positions}) would be exceeded."
        )
        return plan
    new_exposure = portfolio.exposure_inr + plan.notional_inr
    if new_exposure > equity * risk.max_portfolio_exposure_pct / 100 + 1e-6:
        plan.rejections.append(
            f"Portfolio exposure limit breached: ₹{new_exposure:,.2f} > "
            f"{risk.max_portfolio_exposure_pct:.0f}% of equity."
        )
        return plan
    if portfolio.realized_pnl_today_inr <= -equity * risk.daily_loss_limit_pct / 100:
        plan.rejections.append("Daily simulated loss limit reached — new trades blocked.")
        return plan
    # Max drawdown check
    if portfolio.peak_equity_inr:
        dd = 1 - equity / portfolio.peak_equity_inr
        if dd * 100 >= risk.max_drawdown_pct:
            plan.rejections.append(
                f"Max drawdown limit hit ({dd * 100:.1f}% ≥ {risk.max_drawdown_pct:.0f}%)."
            )
            return plan

    plan.accepted = True
    if plan.est_round_trip_costs["round_trip_total"] > 0.10 * plan.notional_inr:
        plan.notes.append(
            "⚠ Estimated round-trip costs exceed 10% of notional — typical for very "
            "small positions. Consider skipping setups that cannot justify the costs."
        )
    plan.notes.append(
        "Estimates only. A stop-loss cannot guarantee its exit price; gaps can cause "
        "larger losses than planned."
    )
    return plan
