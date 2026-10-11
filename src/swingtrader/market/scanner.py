"""Stock scanner and ranking engine.

Evaluates eligible stocks using verified historical data (from CSV store or
yfinance) and produces a documented, configurable score. Every score is
explained; weak evidence produces NO_CLEAR_SETUP rather than a forced pick.

Scoring is NOT a prediction. It is a transparent aggregation of rule outcomes.
No look-ahead: indicators use only past rows; the latest bar is the decision bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from swingtrader.core.settings import StrategySettings
from swingtrader.strategies.indicators import add_indicators
from swingtrader.strategies.signals import evaluate_trend_pullback


@dataclass
class ScoreComponent:
    name: str
    score: float  # 0..weight
    weight: float
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "name": self.name, "score": round(self.score, 2),
            "weight": self.weight, "passed": self.passed, "detail": self.detail,
        }


@dataclass
class ScanResult:
    symbol: str
    name: str = ""
    sector: str = "Other"
    total_score: float = 0.0
    max_score: float = 0.0
    verdict: str = "NO_CLEAR_SETUP"  # STRONG | INTERESTING | WEAK | NO_CLEAR_SETUP | NO_DATA
    components: list[ScoreComponent] = field(default_factory=list)
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    reward_risk: float | None = None
    data_ts: str = ""
    data_quality: str = "HISTORICAL"
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name, "sector": self.sector,
            "total_score": round(self.total_score, 2),
            "max_score": round(self.max_score, 2),
            "verdict": self.verdict,
            "components": [c.to_dict() for c in self.components],
            "entry": self.entry, "stop": self.stop, "target": self.target,
            "reward_risk": self.reward_risk,
            "data_ts": self.data_ts, "data_quality": self.data_quality,
            "reasons": self.reasons, "risks": self.risks, "error": self.error,
        }


# Default component weights (configurable via StrategySettings or overrides).
DEFAULT_WEIGHTS: dict[str, float] = {
    "trend": 20.0,
    "momentum": 15.0,
    "volume": 10.0,
    "structure": 15.0,   # pullback / breakout setup via signal engine
    "volatility": 10.0,  # ATR-based tradability
    "liquidity": 10.0,   # ADTV proxy
    "relative_strength": 10.0,  # vs Nifty (caller supplies benchmark change)
    "risk_geometry": 10.0,  # R:R after costs
}

STRONG_THRESHOLD = 70.0
INTERESTING_THRESHOLD = 50.0


def scan_stock(
    symbol: str,
    df: pd.DataFrame,
    params: StrategySettings,
    *,
    name: str = "",
    sector: str = "Other",
    benchmark_change_pct: float | None = None,
    weights: dict[str, float] | None = None,
    min_rows: int | None = None,
) -> ScanResult:
    """Score one stock from a daily OHLCV frame (chronological, no NaN tail).

    All indicators are computed causally on the provided frame. The decision
    uses only the last bar — no future rows are ever accessed.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    need = min_rows or (params.sma_slow + 5)
    res = ScanResult(symbol=symbol.upper(), name=name, sector=sector)
    res.max_score = sum(w.values())

    if df is None or len(df) < need:
        res.verdict = "NO_DATA"
        res.error = f"Insufficient history: {0 if df is None else len(df)} rows < {need}."
        res.risks.append("Not enough data to evaluate — no score computed.")
        return res

    res.data_ts = str(df["ts"].iloc[-1]) if "ts" in df.columns else ""

    ind = add_indicators(df, params)
    last = ind.iloc[-1]

    # ── Trend (close vs SMAs, fast vs slow) ──
    trend_score = 0.0
    trend_detail = []
    if pd.notna(last.get("sma_slow")) and last["close"] > last["sma_slow"]:
        trend_score += w["trend"] * 0.5
        trend_detail.append("close > slow SMA")
    if pd.notna(last.get("sma_fast")) and pd.notna(last.get("sma_slow")):
        if last["sma_fast"] > last["sma_slow"]:
            trend_score += w["trend"] * 0.5
            trend_detail.append("fast SMA > slow SMA")
    res.components.append(ScoreComponent(
        "trend", trend_score, w["trend"], trend_score >= w["trend"] * 0.5,
        "; ".join(trend_detail) or "Trend filters failed",
    ))

    # ── Momentum (RSI band) ──
    mom_score = 0.0
    mom_detail = []
    rsi = last.get("rsi")
    if pd.notna(rsi):
        if params.rsi_os <= rsi <= params.rsi_ob:
            mom_score = w["momentum"]  # in the sweet zone
            mom_detail.append(f"RSI {rsi:.1f} in [{params.rsi_os:.0f}, {params.rsi_ob:.0f}]")
        elif rsi < params.rsi_os:
            mom_score = w["momentum"] * 0.3
            mom_detail.append(f"RSI {rsi:.1f} oversold (risky catch)")
        else:
            mom_detail.append(f"RSI {rsi:.1f} overbought")
    res.components.append(ScoreComponent(
        "momentum", mom_score, w["momentum"], mom_score >= w["momentum"] * 0.7,
        "; ".join(mom_detail) or "RSI unavailable",
    ))

    # ── Volume (vs its own SMA) ──
    vol_score = 0.0
    vol_detail = []
    if pd.notna(last.get("vol_sma")) and last["vol_sma"] > 0:
        rv = last["volume"] / last["vol_sma"]
        if rv >= 1.5:
            vol_score = w["volume"]
            vol_detail.append(f"relative volume {rv:.2f}x (strong)")
        elif rv >= 1.0:
            vol_score = w["volume"] * 0.6
            vol_detail.append(f"relative volume {rv:.2f}x (adequate)")
        else:
            vol_detail.append(f"relative volume {rv:.2f}x (weak)")
    res.components.append(ScoreComponent(
        "volume", vol_score, w["volume"], vol_score >= w["volume"] * 0.6,
        "; ".join(vol_detail) or "Volume SMA unavailable",
    ))

    # ── Structure (reuse the rule-based signal engine) ──
    sig = evaluate_trend_pullback(symbol, ind, params)
    struct_score = 0.0
    struct_detail = []
    if sig.action == "BUY_SETUP":
        struct_score = w["structure"]
        struct_detail.append("BUY_SETUP: all core rules passed")
        res.entry = sig.entry_reference
        res.stop = sig.stop_price
        res.target = sig.target_price
        res.reward_risk = sig.reward_risk
    elif sig.action == "WAIT":
        struct_score = w["structure"] * 0.4
        struct_detail.append("WAIT: trend present, setup incomplete")
    else:
        struct_detail.append("NO_TRADE from signal engine")
        if sig.reasons:
            struct_detail.append(sig.reasons[0])
    res.components.append(ScoreComponent(
        "structure", struct_score, w["structure"], struct_score >= w["structure"] * 0.8,
        "; ".join(struct_detail),
    ))

    # ── Volatility / tradability (ATR as % of price) ──
    volat_score = 0.0
    volat_detail = []
    atr = last.get("atr")
    if pd.notna(atr) and last["close"] > 0:
        atr_pct = 100 * float(atr) / float(last["close"])
        if 1.0 <= atr_pct <= 4.0:
            volat_score = w["volatility"]
            volat_detail.append(f"ATR% {atr_pct:.1f}% (tradable band)")
        elif 0.5 <= atr_pct < 1.0:
            volat_score = w["volatility"] * 0.5
            volat_detail.append(f"ATR% {atr_pct:.1f}% (low volatility)")
        else:
            volat_detail.append(f"ATR% {atr_pct:.1f}% (extreme — risk)")
            res.risks.append(f"Extreme volatility: ATR {atr_pct:.1f}% of price.")
    res.components.append(ScoreComponent(
        "volatility", volat_score, w["volatility"], volat_score >= w["volatility"] * 0.5,
        "; ".join(volat_detail) or "ATR unavailable",
    ))

    # ── Liquidity (average daily traded value over last 20 rows) ──
    liq_score = 0.0
    liq_detail = []
    if len(ind) >= 20:
        adtv = float((ind["close"].tail(20) * ind["volume"].tail(20)).mean())
        if adtv >= 10_000_000:  # Rs 1 crore
            liq_score = w["liquidity"]
            liq_detail.append(f"ADTV Rs {adtv/1e7:.1f} Cr (liquid)")
        elif adtv >= 2_000_000:
            liq_score = w["liquidity"] * 0.6
            liq_detail.append(f"ADTV Rs {adtv/1e7:.2f} Cr (moderate)")
        else:
            liq_detail.append(f"ADTV Rs {adtv/1e7:.2f} Cr (thin — slippage risk)")
            res.risks.append("Low liquidity — expect wider spreads and slippage.")
    res.components.append(ScoreComponent(
        "liquidity", liq_score, w["liquidity"], liq_score >= w["liquidity"] * 0.6,
        "; ".join(liq_detail) or "ADTV unavailable",
    ))

    # ── Relative strength vs benchmark (if provided) ──
    rs_score = 0.0
    rs_detail = []
    if benchmark_change_pct is not None and len(ind) >= 22:
        stock_1m = 100 * (float(ind["close"].iloc[-1]) / float(ind["close"].iloc[-21]) - 1)
        rs = stock_1m - benchmark_change_pct
        if rs > 5:
            rs_score = w["relative_strength"]
            rs_detail.append(f"1M RS {rs:+.1f}% vs benchmark (strong)")
        elif rs > 0:
            rs_score = w["relative_strength"] * 0.6
            rs_detail.append(f"1M RS {rs:+.1f}% vs benchmark (positive)")
        else:
            rs_detail.append(f"1M RS {rs:+.1f}% vs benchmark (lagging)")
    res.components.append(ScoreComponent(
        "relative_strength", rs_score, w["relative_strength"],
        rs_score >= w["relative_strength"] * 0.6,
        "; ".join(rs_detail) or "Benchmark not supplied",
    ))

    # ── Risk geometry (R:R from signal, if available) ──
    risk_score = 0.0
    risk_detail = []
    if res.reward_risk is not None:
        if res.reward_risk >= params.min_reward_risk * 1.2:
            risk_score = w["risk_geometry"]
            risk_detail.append(f"R:R {res.reward_risk:.2f} (comfortable)")
        elif res.reward_risk >= params.min_reward_risk:
            risk_score = w["risk_geometry"] * 0.7
            risk_detail.append(f"R:R {res.reward_risk:.2f} (meets minimum)")
        else:
            risk_detail.append(f"R:R {res.reward_risk:.2f} (below minimum)")
    res.components.append(ScoreComponent(
        "risk_geometry", risk_score, w["risk_geometry"],
        risk_score >= w["risk_geometry"] * 0.7,
        "; ".join(risk_detail) or "No entry/stop geometry",
    ))

    # ── Aggregate ──
    res.total_score = sum(c.score for c in res.components)

    # Verdict
    if res.total_score >= STRONG_THRESHOLD and sig.action == "BUY_SETUP":
        res.verdict = "STRONG"
        res.reasons.append("Strong score with a full BUY_SETUP signal.")
    elif res.total_score >= INTERESTING_THRESHOLD:
        res.verdict = "INTERESTING"
        res.reasons.append("Moderate score — worth watching; setup not fully confirmed.")
    elif res.total_score >= INTERESTING_THRESHOLD * 0.6:
        res.verdict = "WEAK"
        res.reasons.append("Weak evidence — no clear trade basis.")
    else:
        res.verdict = "NO_CLEAR_SETUP"
        res.reasons.append("Evidence too weak for any trade plan.")

    # Generic risk notes
    if not res.risks:
        res.risks.append("Past performance does not predict future results.")
    return res


def rank_stocks(results: list[ScanResult]) -> list[ScanResult]:
    """Sort scan results by total_score descending; NO_DATA last."""
    order = {"STRONG": 0, "INTERESTING": 1, "WEAK": 2, "NO_CLEAR_SETUP": 3, "NO_DATA": 4}
    return sorted(
        results,
        key=lambda r: (order.get(r.verdict, 9), -r.total_score, r.symbol),
    )


def explain_exclusion(result: ScanResult) -> str:
    """Human-readable explanation of why a stock was excluded / downgraded."""
    failed = [c for c in result.components if not c.passed]
    if not failed:
        return "All components passed — included in ranking."
    parts = [f"{c.name}: {c.detail}" for c in failed]
    return "Excluded/downgraded — " + "; ".join(parts)
