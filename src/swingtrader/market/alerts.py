"""Alert / monitoring engine.

Checks watchlist candidates and paper positions against configurable conditions
and produces timestamped alerts with the exact triggering condition. Never
silently changes a stop or target. Duplicate alerts are suppressed via a
cooldown per (symbol, condition_key).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger(__name__)


@dataclass
class Alert:
    id: str
    ts: str
    symbol: str
    condition_key: str  # stable key for dedupe, e.g. "stop_near:RELIANCE"
    severity: str  # INFO | WARNING | CRITICAL
    title: str
    detail: str
    evidence: dict = field(default_factory=dict)
    delivered: bool = False
    delivery_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "ts": self.ts, "symbol": self.symbol,
            "condition_key": self.condition_key, "severity": self.severity,
            "title": self.title, "detail": self.detail,
            "evidence": self.evidence, "delivered": self.delivered,
            "delivery_error": self.delivery_error,
        }


@dataclass
class AlertRule:
    key: str
    description: str
    enabled: bool = True
    cooldown_minutes: int = 60


DEFAULT_RULES: dict[str, AlertRule] = {
    "stop_near": AlertRule("stop_near", "Price within 2% of stop-loss"),
    "target_near": AlertRule("target_near", "Price within 2% of target"),
    "breakout": AlertRule("breakout", "Price breaks above recent resistance"),
    "breakdown": AlertRule("breakdown", "Price breaks below recent support"),
    "volume_spike": AlertRule("volume_spike", "Volume > 2x its 20-day average"),
    "stale_data": AlertRule("stale_data", "Data older than stale threshold"),
    "entry_valid": AlertRule("entry_valid", "Entry conditions became valid"),
    "big_move": AlertRule("big_move", "Single-session move > 3%"),
}


class AlertEngine:
    """Evaluates alert rules against symbol snapshots and produces Alerts."""

    def __init__(self, rules: dict[str, AlertRule] | None = None) -> None:
        self.rules = rules or dict(DEFAULT_RULES)
        self._last_fired: dict[str, datetime] = {}
        self._counter = 0

    def _cooldown_ok(self, key: str) -> bool:
        rule = self.rules.get(key.split(":")[0])
        cd = rule.cooldown_minutes if rule else 60
        last = self._last_fired.get(key)
        if last is None:
            return True
        return (datetime.now(UTC) - last).total_seconds() >= cd * 60

    def _make(self, symbol: str, rule_key: str, severity: str, title: str,
              detail: str, evidence: dict) -> Alert | None:
        key = f"{rule_key}:{symbol}"
        rule = self.rules.get(rule_key)
        if rule and not rule.enabled:
            return None
        if not self._cooldown_ok(key):
            return None
        self._counter += 1
        self._last_fired[key] = datetime.now(UTC)
        return Alert(
            id=f"A{self._counter:06d}",
            ts=datetime.now(UTC).isoformat(),
            symbol=symbol.upper(), condition_key=key,
            severity=severity, title=title, detail=detail, evidence=evidence,
        )

    def check_symbol(
        self,
        symbol: str,
        *,
        price: float | None,
        stop: float | None = None,
        target: float | None = None,
        support: float | None = None,
        resistance: float | None = None,
        volume: float | None = None,
        avg_volume: float | None = None,
        prev_close: float | None = None,
        data_age_hours: float | None = None,
        stale_after_days: int = 7,
    ) -> list[Alert]:
        """Evaluate all enabled rules for one symbol snapshot."""
        out: list[Alert] = []
        if price is None:
            return out

        if stop is not None and price > 0:
            dist = (price - stop) / price
            if 0 <= dist <= 0.02:
                a = self._make(
                    symbol, "stop_near", "CRITICAL",
                    f"{symbol} within 2% of stop",
                    f"Price ₹{price:,.2f} is {dist*100:.1f}% above stop ₹{stop:,.2f}. "
                    f"Review the position — do not silently move the stop.",
                    {"price": price, "stop": stop, "distance_pct": round(dist*100, 2)},
                )
                if a:
                    out.append(a)

        if target is not None and price > 0:
            dist = (target - price) / price
            if 0 <= dist <= 0.02:
                a = self._make(
                    symbol, "target_near", "INFO",
                    f"{symbol} within 2% of target",
                    f"Price ₹{price:,.2f} is {dist*100:.1f}% below target ₹{target:,.2f}. "
                    f"Targets are not guaranteed profits.",
                    {"price": price, "target": target, "distance_pct": round(dist*100, 2)},
                )
                if a:
                    out.append(a)

        if resistance is not None and price > resistance:
            a = self._make(
                symbol, "breakout", "WARNING",
                f"{symbol} above recent resistance",
                f"Price ₹{price:,.2f} crossed resistance ₹{resistance:,.2f}. "
                f"Confirm with volume before treating as a breakout.",
                {"price": price, "resistance": resistance},
            )
            if a:
                out.append(a)

        if support is not None and price < support:
            a = self._make(
                symbol, "breakdown", "CRITICAL",
                f"{symbol} below recent support",
                f"Price ₹{price:,.2f} broke support ₹{support:,.2f}.",
                {"price": price, "support": support},
            )
            if a:
                out.append(a)

        if volume and avg_volume and avg_volume > 0 and volume / avg_volume >= 2.0:
            a = self._make(
                symbol, "volume_spike", "WARNING",
                f"{symbol} volume spike",
                f"Volume {volume:,.0f} is {volume/avg_volume:.1f}x the 20-day average.",
                {"volume": volume, "avg_volume": avg_volume},
            )
            if a:
                out.append(a)

        if prev_close and price > 0:
            move_pct = abs(100 * (price - prev_close) / prev_close)
            if move_pct >= 3.0:
                direction = "up" if price > prev_close else "down"
                a = self._make(
                    symbol, "big_move", "WARNING",
                    f"{symbol} moved {move_pct:.1f}% {direction}",
                    f"Single-session move of {move_pct:.1f}% — review open positions.",
                    {"price": price, "prev_close": prev_close, "move_pct": round(move_pct, 2)},
                )
                if a:
                    out.append(a)

        if data_age_hours is not None and data_age_hours > stale_after_days * 24:
            a = self._make(
                symbol, "stale_data", "WARNING",
                f"{symbol} data is stale",
                f"Last data is {data_age_hours/24:.1f} days old (threshold "
                f"{stale_after_days} days). Decisions on stale data are blocked.",
                {"age_hours": data_age_hours, "threshold_days": stale_after_days},
            )
            if a:
                out.append(a)

        return out
