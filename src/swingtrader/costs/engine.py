"""Centralized Indian cash-equity transaction-cost estimates.

UNIT CONVENTION:
    Every field in CostAssumptions ending in `_pct` is a PERCENTAGE.
    The engine computes: charge = turnover_inr * pct_field / 100
    so pct_field = 0.1 means 0.1% of turnover, 18.0 means 18%, etc.

VERIFIED RATES (checked 2026-10-11 against official NSE / SEBI / Stamp Act sources):
    STT (delivery equity)      : 0.1%  of turnover, BOTH buy and sell
    Stamp duty (delivery)      : 0.015% of turnover, BUY side only
    Exchange txn charge (NSE)  : ~0.00297% of turnover (both sides)
    SEBI turnover fee          : 0.0001% of turnover (Rs 10 per crore)
    GST                        : 18% on (brokerage + exchange txn + SEBI)
    Brokerage (delivery)       : 0% at discount brokers (Groww delivery);
                                 full-service may charge 0.03% with Rs 20 min.
    Slippage                   : adverse execution assumption, NOT a statutory
                                 fee; kept separate so users can see it clearly.

Formulas (delivery equity):
    brokerage      = max(turnover * brokerage_pct/100, brokerage_min_inr)
    stt            = turnover * stt_side_pct/100
    exchange_txn   = turnover * exchange_txn_charge_pct/100
    sebi           = turnover * sebi_charge_pct/100
    gst            = (brokerage + exchange_txn + sebi) * gst_pct/100
    stamp_duty     = turnover * stamp_duty_buy_pct/100   (buy side only)
    slippage_cost  = turnover * slippage_pct/100         (price impact, not a fee)

Sources (verified 2026-10-11):
    - NSE STT/Stamp/SEBI: nseindia.com first-time-investor pages
    - SEBI turnover: Rs 10 per crore (0.0001%)
"""

from __future__ import annotations

from typing import Literal

from swingtrader.core.settings import CostAssumptions

Side = Literal["BUY", "SELL"]


def apply_slippage(price: float, side: Side, costs: CostAssumptions) -> float:
    """Worse execution price: buy higher, sell lower.

    This is an execution assumption (price impact / spread), NOT a statutory
    fee. It is applied to the fill price, not added as a separate charge.
    """
    factor = 1 + costs.slippage_pct / 100 if side == "BUY" else 1 - costs.slippage_pct / 100
    return round(price * factor, 2)


def estimate_costs(turnover_inr: float, side: Side, costs: CostAssumptions) -> dict[str, float]:
    """Estimated statutory charges for one full buy or sell of `turnover_inr` notional.

    Does NOT include slippage (slippage adjusts the fill price via apply_slippage).
    Buy side includes stamp duty; sell side does not. STT applies to both sides
    for delivery equity.
    """
    if turnover_inr < 0:
        raise ValueError("turnover must be non-negative")
    t = turnover_inr
    brokerage = max(t * costs.brokerage_pct / 100, costs.brokerage_min_inr) if t > 0 else 0.0
    stt = t * (costs.stt_buy_pct if side == "BUY" else costs.stt_sell_pct) / 100
    exchange_txn = t * costs.exchange_txn_charge_pct / 100
    sebi = t * costs.sebi_charge_pct / 100
    gst = (brokerage + exchange_txn + sebi) * costs.gst_pct / 100
    stamp = t * costs.stamp_duty_buy_pct / 100 if side == "BUY" else 0.0
    total = brokerage + stt + exchange_txn + sebi + gst + stamp
    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(exchange_txn, 2),
        "sebi": round(sebi, 2),
        "gst": round(gst, 2),
        "stamp_duty": round(stamp, 2),
        "total": round(total, 2),
    }


def per_share_buy_cost(price: float, costs: CostAssumptions) -> float:
    """Statutory buy-side cost per share at `price` (no slippage)."""
    return estimate_costs(price, "BUY", costs)["total"]


def per_share_sell_cost(price: float, costs: CostAssumptions) -> float:
    """Statutory sell-side cost per share at `price` (no slippage)."""
    return estimate_costs(price, "SELL", costs)["total"]


def per_share_round_trip_cost(price: float, costs: CostAssumptions) -> float:
    """Combined buy+sell statutory cost per share at `price` (no slippage)."""
    return per_share_buy_cost(price, costs) + per_share_sell_cost(price, costs)


def round_trip_cost_estimate(turnover_inr: float, costs: CostAssumptions) -> dict[str, float]:
    """Combined buy+sell statutory cost estimate for one round trip of the same notional.

    Does NOT include slippage.
    """
    b = estimate_costs(turnover_inr, "BUY", costs)
    s = estimate_costs(turnover_inr, "SELL", costs)
    total = b["total"] + s["total"]
    return {
        "buy_total": b["total"],
        "sell_total": s["total"],
        "round_trip_total": round(total, 2),
        "round_trip_pct": round(100 * total / turnover_inr, 4) if turnover_inr else 0.0,
    }


def cost_warning(costs: CostAssumptions) -> str:
    if costs.config_verified_date == "UNVERIFIED":
        return (
            "⚠ Cost rates are UNVERIFIED placeholders. Confirm current brokerage, STT, "
            "GST, stamp duty and exchange charges with official sources before relying "
            "on net-profit figures."
        )
    return (
        f"Cost schedule verified against official NSE/SEBI/Stamp sources on "
        f"{costs.config_verified_date}."
    )
