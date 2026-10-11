"""Centralized Indian cash-equity transaction-cost estimates.

IMPORTANT: All rates live in CostAssumptions with a `config_verified_date`.
While that field is "UNVERIFIED", every consumer must display results as
unverified estimates. Buy-side and sell-side charges are modelled separately
(stamp duty applies on buys; STT differs by side for delivery).

Formulas (delivery equity, as commonly applicable — VERIFY before trusting):
  brokerage      = max(turnover * brokerage_pct/100, brokerage_min_inr)
  stt            = turnover * stt_side_pct/100
  exchange_txn   = turnover * exchange_txn_charge_pct/100
  sebi           = turnover * sebi_charge_pct/100
  gst            = (brokerage + exchange_txn + sebi) * gst_pct/100
  stamp_duty     = turnover * stamp_duty_buy_pct/100   (buy side only)
  slippage_cost  = turnover * slippage_pct/100         (price impact, not a fee)
"""

from __future__ import annotations

from typing import Literal

from swingtrader.core.settings import CostAssumptions

Side = Literal["BUY", "SELL"]


def apply_slippage(price: float, side: Side, costs: CostAssumptions) -> float:
    """Worse execution price: buy higher, sell lower."""
    factor = 1 + costs.slippage_pct / 100 if side == "BUY" else 1 - costs.slippage_pct / 100
    return round(price * factor, 2)


def estimate_costs(turnover_inr: float, side: Side, costs: CostAssumptions) -> dict[str, float]:
    """Estimated charges for one full buy or sell of `turnover_inr` notional."""
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


def round_trip_cost_estimate(turnover_inr: float, costs: CostAssumptions) -> dict[str, float]:
    """Combined buy+sell cost estimate for one round trip of the same notional."""
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
    return f"Cost schedule marked as verified on {costs.config_verified_date}."
