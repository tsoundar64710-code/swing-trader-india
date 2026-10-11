"""Transparent, rule-based signal generation.

Every signal records the rules evaluated, values used, and explicit reasons
for NO TRADE. Rules are checked in strict prerequisite order:

1. Data integrity  2. Eligibility  3. Liquidity  4. Risk  5. Strategy rules
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from swingtrader.core.settings import StrategySettings
from swingtrader.strategies.indicators import add_indicators

ACTIONS = ("BUY_SETUP", "WAIT", "SELL_EXIT_SETUP", "NO_TRADE")


@dataclass
class SignalResult:
    symbol: str
    action: str  # one of ACTIONS
    signal_ts: str  # when the signal was computed (UTC)
    data_ts: str  # last candle timestamp used
    strategy_name: str = "trend_pullback_v1"
    data_status: str = "ok"  # ok | stale | insufficient
    entry_reference: float | None = None
    invalidation_level: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    reward_risk: float | None = None
    indicators: dict = field(default_factory=dict)
    rules_satisfied: list[str] = field(default_factory=list)
    rules_failed: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    expiry_note: str = "Review on the next daily close."

    def to_details_json(self) -> str:
        import json

        return json.dumps(
            {
                "strategy": self.strategy_name,
                "data_status": self.data_status,
                "entry_reference": self.entry_reference,
                "invalidation_level": self.invalidation_level,
                "stop_price": self.stop_price,
                "target_price": self.target_price,
                "reward_risk": self.reward_risk,
                "indicators": self.indicators,
                "rules_satisfied": self.rules_satisfied,
                "rules_failed": self.rules_failed,
                "reasons": self.reasons,
                "expiry_note": self.expiry_note,
                "disclaimer": (
                    "Research output only — not investment advice and not an "
                    "automatic order. Stops can gap through. Costs reduce returns."
                ),
            },
            default=str,
        )


def _no_trade(symbol: str, data_ts: str, reason: str, status: str = "insufficient") -> SignalResult:
    return SignalResult(
        symbol=symbol,
        action="NO_TRADE",
        signal_ts=datetime.now(UTC).isoformat(),
        data_ts=data_ts or "none",
        data_status=status,
        reasons=[reason],
        rules_failed=["data_integrity" if status != "ok" else "strategy_rules"],
    )


def trend_pullback_signal(
    symbol: str,
    df: pd.DataFrame,
    params: StrategySettings,
    *,
    stale: bool = False,
) -> SignalResult:
    """Long-only swing setup: established uptrend + pullback + momentum filter.

    This is a research candidate, not a proven strategy.
    """
    need = params.sma_slow + 5
    if df is None or len(df) < need:
        n = 0 if df is None else len(df)
        return _no_trade(
            symbol,
            str(df["ts"].iloc[-1]) if df is not None and len(df) else "",
            f"Insufficient history: {n} rows < {need} required for slow SMA warm-up.",
        )
    if stale:
        last = str(df["ts"].iloc[-1])
        r = _no_trade(
            symbol, last, "Data is stale — decisions on stale data are blocked.", status="stale"
        )
        r.rules_failed = ["data_freshness"]
        return r

    ind = add_indicators(df, params)
    return evaluate_trend_pullback(symbol, ind, params)


def evaluate_trend_pullback(
    symbol: str, ind: pd.DataFrame, params: StrategySettings
) -> SignalResult:
    """Evaluate rules on a frame that already contains indicator columns.

    `ind` must be chronologically ordered; only its final row and the final
    three lows are used, so callers can pass a prefix window without leakage.
    """
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    data_ts = str(last["ts"])

    needed = ("sma_slow", "sma_fast", "rsi", "atr")
    if any(pd.isna(last[c]) for c in needed):
        return _no_trade(symbol, data_ts, "Indicators not fully warmed up on the latest bar.")

    ok: list[str] = []
    failed: list[str] = []
    reasons: list[str] = []

    # R1: close above slow SMA (long-term trend up)
    if last["close"] > last["sma_slow"]:
        ok.append("R1 close > slow SMA")
    else:
        failed.append("R1 close <= slow SMA")
        reasons.append("Trend filter failed: price is not above the slow moving average.")

    # R2: fast SMA above slow SMA (trend structure)
    if last["sma_fast"] > last["sma_slow"]:
        ok.append("R2 fast SMA > slow SMA")
    else:
        failed.append("R2 fast SMA <= slow SMA")
        reasons.append("Trend structure failed: short average is not above the long average.")

    # R3: pullback — recent low near/into the fast-SMA zone (last 3 bars)
    recent_lows = ind["low"].tail(3)
    pullback = bool((recent_lows <= last["sma_fast"] * 1.01).any())
    if pullback:
        ok.append("R3 pullback toward fast SMA (3 bars)")
    else:
        failed.append("R3 no pullback")
        reasons.append("No pullback: price has not retreated toward the short average.")

    # R4: momentum not overbought
    if last["rsi"] < params.rsi_ob:
        ok.append(f"R4 RSI {last['rsi']:.1f} < {params.rsi_ob:.0f}")
    else:
        failed.append("R4 RSI overbought")
        reasons.append(f"Momentum filter failed: RSI {last['rsi']:.1f} is overbought.")

    # R5: volume confirmation vs its own average
    if pd.notna(last["vol_sma"]) and last["volume"] >= last["vol_sma"]:
        ok.append("R5 volume >= volume SMA")
    else:
        failed.append("R5 weak volume")
        reasons.append("Volume confirmation missing: latest volume below its average.")

    # R6: still above invalidation (slow SMA) — structural stop reference
    invalidation = float(last["sma_slow"])
    if last["close"] > invalidation:
        ok.append("R6 close > invalidation (slow SMA)")
    else:
        failed.append("R6 below invalidation")
        reasons.append("Invalidation breached: close is at/below the slow average.")

    satisfied_core = all(
        any(x.startswith(p) for x in ok)
        for p in ("R1", "R2", "R3", "R4", "R6")
    )

    ind_values = {
        "close": round(float(last["close"]), 2),
        "sma_fast": round(float(last["sma_fast"]), 2),
        "sma_slow": round(float(last["sma_slow"]), 2),
        "rsi": round(float(last["rsi"]), 2),
        "atr": round(float(last["atr"]), 2),
        "volume": float(last["volume"]),
        "vol_sma": None if pd.isna(last["vol_sma"]) else float(last["vol_sma"]),
        "sup_20": None if pd.isna(last["sup_20"]) else round(float(last["sup_20"]), 2),
        "res_20": None if pd.isna(last["res_20"]) else round(float(last["res_20"]), 2),
        "prev_close": round(float(prev["close"]), 2),
    }

    if not satisfied_core:
        action = "WAIT" if any(x.startswith(("R1", "R2")) for x in ok) else "NO_TRADE"
        if not reasons:
            reasons.append("One or more core rules failed; no entry basis.")
        sig = SignalResult(
            symbol=symbol,
            action=action,
            signal_ts=datetime.now(UTC).isoformat(),
            data_ts=data_ts,
            indicators=ind_values,
            rules_satisfied=ok,
            rules_failed=failed,
            reasons=reasons,
        )
        return sig

    entry = float(last["close"])
    stop = entry - float(last["atr"]) * params.atr_stop_multiplier
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return _no_trade(symbol, data_ts, "Invalid stop geometry (stop >= entry).")
    target = entry + params.min_reward_risk * risk_per_share
    rr = (target - entry) / risk_per_share

    if rr < params.min_reward_risk:
        failed.append("R7 reward:risk below minimum")
        return SignalResult(
            symbol=symbol,
            action="NO_TRADE",
            signal_ts=datetime.now(UTC).isoformat(),
            data_ts=data_ts,
            indicators=ind_values,
            rules_satisfied=ok,
            rules_failed=failed,
            reasons=[f"Reward-to-risk {rr:.2f} < minimum {params.min_reward_risk:.2f}."],
        )

    ok.append(f"R7 reward:risk {rr:.2f} >= {params.min_reward_risk:.2f}")
    reasons.append(
        "All core rules satisfied: trend, pullback, momentum and structure filters passed."
    )
    if "R5 weak volume" in failed:
        reasons.append("Note: volume confirmation failed — treat this setup with extra caution.")

    return SignalResult(
        symbol=symbol,
        action="BUY_SETUP",
        signal_ts=datetime.now(UTC).isoformat(),
        data_ts=data_ts,
        entry_reference=round(entry, 2),
        invalidation_level=round(invalidation, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        reward_risk=round(rr, 2),
        indicators=ind_values,
        rules_satisfied=ok,
        rules_failed=failed,
        reasons=reasons,
        expiry_note="Setup expires if the next daily close breaks the invalidation level.",
    )
