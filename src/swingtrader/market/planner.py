"""Trade planning screen.

Builds a complete, conditional trade plan for a candidate: entry range,
stop, targets, R:R after costs, affordable quantity under risk limits,
max rupee loss, full cost breakdown, invalidation conditions, and reasons
to avoid. Never claims certainty about timing or outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from swingtrader.core.settings import AppSettings
from swingtrader.costs.engine import (
    estimate_costs,
    per_share_buy_cost,
    per_share_round_trip_cost,
)
from swingtrader.risk.sizing import PortfolioState, size_position


@dataclass
class TradePlan:
    symbol: str
    name: str = ""
    setup_type: str = ""
    rationale: str = ""
    latest_price: float | None = None
    price_timestamp: str = ""
    price_quality: str = "HISTORICAL"
    price_source: str = ""

    entry_low: float | None = None
    entry_high: float | None = None
    entry_condition: str = ""
    stop_price: float | None = None
    stop_reason: str = ""
    target1: float | None = None
    target2: float | None = None
    reward_risk: float | None = None
    reward_risk_after_costs: float | None = None

    qty: int = 0
    notional_inr: float = 0.0
    max_loss_inr: float = 0.0
    buy_costs: dict = field(default_factory=dict)
    round_trip_costs: dict = field(default_factory=dict)
    slippage_note: str = ""

    holding_period: str = "swing (days to weeks)"
    upcoming_events: list[str] = field(default_factory=list)
    reasons_to_avoid: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    plan_accepted: bool = False
    rejections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def build_trade_plan(
    symbol: str,
    *,
    name: str = "",
    setup_type: str = "trend_pullback_v1",
    rationale: str = "",
    latest_price: float | None,
    price_timestamp: str = "",
    price_quality: str = "HISTORICAL",
    price_source: str = "",
    entry_reference: float,
    stop_price: float,
    target_price: float | None = None,
    portfolio: PortfolioState,
    settings: AppSettings,
    liquidity_note: str = "",
    extra_risks: list[str] | None = None,
) -> TradePlan:
    """Construct a full conditional trade plan with cost-aware sizing."""
    plan = TradePlan(
        symbol=symbol.upper(), name=name, setup_type=setup_type,
        rationale=rationale, latest_price=latest_price,
        price_timestamp=price_timestamp, price_quality=price_quality,
        price_source=price_source,
    )
    costs = settings.costs

    if latest_price is None:
        plan.reasons_to_avoid.append("Latest verified price unavailable — plan blocked.")
        plan.rejections.append("No verified price.")
        return plan

    # Entry band: around the reference, ±0.5% (conditional, not a market order)
    plan.entry_low = round(entry_reference * 0.995, 2)
    plan.entry_high = round(entry_reference * 1.005, 2)
    plan.entry_condition = (
        f"Limit order zone ₹{plan.entry_low:,.2f}–₹{plan.entry_high:,.2f} "
        f"(reference ₹{entry_reference:,.2f}). Setup valid only while price "
        f"stays above the stop."
    )

    plan.stop_price = round(stop_price, 2)
    plan.stop_reason = (
        f"ATR-based structural stop at ₹{plan.stop_price:,.2f}. "
        f"Risk per share ₹{entry_reference - stop_price:,.2f}."
    )

    risk_per_share = entry_reference - stop_price
    if target_price:
        plan.target1 = round(target_price, 2)
        plan.target2 = round(entry_reference + 2 * risk_per_share, 2)
    else:
        plan.target1 = round(entry_reference + 1.5 * risk_per_share, 2)
        plan.target2 = round(entry_reference + 2.5 * risk_per_share, 2)

    # R:R after statutory costs (no slippage in the ratio; slippage noted separately)
    buy_c = per_share_buy_cost(entry_reference, costs)
    sell_c_at_t1 = estimate_costs(plan.target1, "SELL", costs)["total"] if plan.target1 else 0
    net_reward = (plan.target1 - entry_reference) - buy_c - sell_c_at_t1 if plan.target1 else 0
    net_risk = risk_per_share + buy_c + per_share_round_trip_cost(entry_reference, costs) * 0
    plan.reward_risk = round((plan.target1 - entry_reference) / risk_per_share, 2) if (
        plan.target1 and risk_per_share > 0
    ) else None
    plan.reward_risk_after_costs = (
        round(net_reward / net_risk, 2) if net_risk > 0 else None
    )

    # Position sizing via the risk engine
    sized = size_position(entry_reference, stop_price, portfolio, settings)
    plan.qty = sized.qty
    plan.notional_inr = sized.notional_inr
    plan.buy_costs = sized.est_buy_costs
    plan.round_trip_costs = sized.est_round_trip_costs
    plan.plan_accepted = sized.accepted
    plan.rejections = list(sized.rejections)
    plan.notes = list(sized.notes)
    plan.max_loss_inr = round(
        plan.qty * risk_per_share + plan.buy_costs.get("total", 0), 2
    ) if plan.qty else 0.0

    # Slippage note (separate from fees)
    plan.slippage_note = (
        f"Assumed adverse slippage {costs.slippage_pct}% — fill may be worse "
        f"than reference. Not included in statutory cost totals above."
    )

    # Invalidation conditions
    plan.invalidation_conditions = [
        f"Daily close below ₹{plan.stop_price:,.2f} invalidates the setup.",
        "Gap-down through the stop can fill far below the stop price.",
        "A change in the original signal rules (trend break) voids this plan.",
        "Stale or missing price data blocks any execution decision.",
    ]

    # Reasons to avoid
    if liquidity_note:
        plan.reasons_to_avoid.append(liquidity_note)
    if extra_risks:
        plan.reasons_to_avoid.extend(extra_risks)
    if plan.reward_risk_after_costs is not None and plan.reward_risk_after_costs < 1.0:
        plan.reasons_to_avoid.append(
            f"R:R after costs ({plan.reward_risk_after_costs:.2f}) is below 1.0 — "
            f"poor asymmetry once charges are included."
        )
    if plan.qty == 0:
        plan.reasons_to_avoid.append("Position sizing produced 0 shares under current limits.")
    plan.reasons_to_avoid.append(
        "This is a conditional research plan, not a recommendation or guarantee."
    )

    plan.holding_period = "swing (3–15 sessions typical for this setup)"
    plan.upcoming_events = [
        "Check earnings calendar before entry (not fetched automatically).",
        "Check for board meetings, dividend dates, and regulatory filings.",
    ]
    plan.notes.append(
        "Timing cannot be known exactly. Entry/exit are conditional levels, "
        "not predictions. Stops can gap. Costs reduce returns."
    )
    return plan
