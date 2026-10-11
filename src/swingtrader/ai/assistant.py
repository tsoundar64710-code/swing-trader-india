"""Rule-based local assistant.

Answers questions using data already in the local database (signals,
positions, cash, watchlist, journal, settings). No external model calls,
no network access, no secret storage. The assistant never gives investment
advice — it reports facts and reminds the user of their own rules.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field


@dataclass
class AssistantReply:
    """Structured reply from the local assistant."""

    answer: str
    data: dict = field(default_factory=dict)
    refused: bool = False  # True when the assistant declines to advise


class Assistant:
    """Rule-based question answering over local trading data."""

    def __init__(self, conn: sqlite3.Connection, settings=None) -> None:
        self.conn = conn
        self.settings = settings

    # ── public API ────────────────────────────────────────────────

    def answer(self, question: str) -> AssistantReply:
        original = question.strip()
        q = original.lower()
        if not q:
            return AssistantReply(
                "Ask me about your watchlist, signals, positions, cash, journal, or strategy rules."
            )

        if q in {"hi", "hello", "hey", "namaste"}:
            return AssistantReply(
                "Hello. I answer questions about your local trading data. "
                "I do not give buy/sell advice."
            )

        advice_words = ("advice", "should i buy", "should i sell", "recommend", "what should i")
        if any(w in q for w in advice_words):
            return AssistantReply(
                "I cannot give investment advice. I can only report facts from your local data: "
                "signals, positions, cash, watchlist, journal entries, and your configured rules.",
                refused=True,
            )

        if "help" in q or "what can you" in q:
            return AssistantReply(
                "I can answer questions about: watchlist, signals, positions, cash/equity, "
                "journal entries, strategy parameters, risk limits, and transaction costs. "
                "I do not give buy/sell recommendations."
            )

        handlers = [
            (r"watchlist|symbols?\s+(?:on|in)\s+my|which stocks", self._watchlist),
            (r"signal|buy.?setup|no.?trade|wait\b", self._signals),
            (r"position|holding|exposure|invested", self._positions),
            (r"\bcash\b|balance|equity|available", self._cash),
            (r"journal|lesson|review|violat", self._journal),
            (r"strategy|sma|rsi|atr|rule|param", self._strategy),
            (r"risk|limit|drawdown|stop.?loss|max", self._risk),
            (r"cost|fee|charge|brokerage|slippage|stt", self._costs),
            (r"status|summary|overview|dashboard|health", self._status),
        ]
        symbol = self._extract_symbol(original)
        if symbol:
            return self._symbol_question(symbol, q)

        for pattern, fn in handlers:
            if re.search(pattern, q):
                return fn()

        return AssistantReply(
            "I could not match that question. Try: 'show my signals', 'what is my cash', "
            "'list watchlist', 'explain strategy', or 'what are my risk limits'."
        )

    # ── handlers ──────────────────────────────────────────────────

    def _watchlist(self) -> AssistantReply:
        rows = self.conn.execute(
            "SELECT i.symbol, w.added_at FROM watchlist w "
            "JOIN instruments i ON i.id=w.instrument_id "
            "ORDER BY w.added_at DESC LIMIT 50"
        ).fetchall()
        if not rows:
            return AssistantReply("Your watchlist is empty. Add symbols on the Watchlist page.")
        lines = [f"- {r['symbol']} (added {(r['added_at'] or '')[:10]})" for r in rows]
        return AssistantReply(
            f"You are watching {len(rows)} symbols:\n" + "\n".join(lines),
            data={"count": len(rows), "symbols": [r["symbol"] for r in rows]},
        )

    def _signals(self) -> AssistantReply:
        rows = self.conn.execute(
            "SELECT i.symbol, s.action, s.details_json, s.created_at FROM signals s "
            "JOIN instruments i ON i.id=s.instrument_id ORDER BY s.id DESC LIMIT 20"
        ).fetchall()
        if not rows:
            return AssistantReply(
                "No signals computed yet. Run the Signal Centre or import data first."
            )
        lines = [
            f"- {r['symbol']}: {r['action']} — {(r['details_json'] or '')[:80]}"
            for r in rows
        ]
        return AssistantReply(
            f"Your {len(rows)} most recent signals:\n" + "\n".join(lines),
            data={"count": len(rows)},
        )

    def _positions(self) -> AssistantReply:
        rows = self.conn.execute(
            "SELECT p.symbol, p.qty, p.avg_cost, p.stop_price FROM positions p WHERE p.qty != 0"
        ).fetchall()
        if not rows:
            return AssistantReply("You have no open paper-trading positions.")
        lines = [
            f"- {r['symbol']}: {r['qty']} @ ₹{r['avg_cost']:.2f}"
            + (f" (stop ₹{r['stop_price']:.2f})" if r["stop_price"] else " (NO STOP SET)")
            for r in rows
        ]
        return AssistantReply(
            f"Open positions ({len(rows)}):\n" + "\n".join(lines),
            data={"count": len(rows)},
        )

    def _cash(self) -> AssistantReply:
        row = self.conn.execute(
            "SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
        bal = row["balance_after"] if row else (
            self.settings.initial_capital_inr if self.settings else 0.0
        )
        return AssistantReply(f"Paper-trading cash balance: ₹{bal:.2f}", data={"cash": bal})

    def _journal(self) -> AssistantReply:
        rows = self.conn.execute(
            "SELECT COALESCE(i.symbol,'General') AS symbol, j.outcome, j.lessons, j.created_at "
            "FROM journal_entries j LEFT JOIN instruments i ON i.id=j.instrument_id "
            "ORDER BY j.id DESC LIMIT 10"
        ).fetchall()
        if not rows:
            return AssistantReply(
                "No journal entries yet. Record your trades on the Journal page."
            )
        lines = []
        for r in rows:
            sym = r["symbol"] or "General"
            out = r["outcome"] or "—"
            lesson = (r["lessons"] or "")[:60]
            lines.append(f"- {sym} [{out}]" + (f": {lesson}" if lesson else ""))
        return AssistantReply(
            f"Your {len(rows)} most recent journal entries:\n" + "\n".join(lines),
            data={"count": len(rows)},
        )

    def _strategy(self) -> AssistantReply:
        if not self.settings:
            return AssistantReply("Strategy settings not loaded.")
        s = self.settings.strategy
        return AssistantReply(
            "Current strategy (trend_pullback_v1):\n"
            f"- Fast SMA: {s.sma_fast}, Slow SMA: {s.sma_slow}\n"
            f"- RSI period {s.rsi_period}, overbought {s.rsi_ob}, oversold {s.rsi_os}\n"
            f"- ATR period {s.atr_period}, stop multiplier {s.atr_stop_multiplier}\n"
            f"- Minimum R:R: {s.min_reward_risk}\n"
            "Rules: close > slow SMA, fast SMA > slow SMA, pullback to fast SMA, "
            "RSI below overbought, volume confirmation, above invalidation, R:R acceptable.",
            data={"sma_fast": s.sma_fast, "sma_slow": s.sma_slow},
        )

    def _risk(self) -> AssistantReply:
        if not self.settings:
            return AssistantReply("Risk settings not loaded.")
        r = self.settings.risk
        return AssistantReply(
            "Your risk limits:\n"
            f"- Max position: {r.max_position_pct}% of equity\n"
            f"- Max portfolio exposure: {r.max_portfolio_exposure_pct}%\n"
            f"- Max risk per trade: {r.max_risk_per_trade_pct}%\n"
            f"- Max open positions: {r.max_open_positions}\n"
            f"- Max drawdown: {r.max_drawdown_pct}%\n"
            f"- Daily loss limit: {r.daily_loss_limit_pct}%",
            data={"max_position_pct": r.max_position_pct},
        )

    def _costs(self) -> AssistantReply:
        if not self.settings:
            return AssistantReply("Cost settings not loaded.")
        c = self.settings.costs
        verified = c.config_verified_date != "UNVERIFIED"
        warn = "" if verified else (
            "\n⚠ Rates are UNVERIFIED placeholders — verify with official sources."
        )
        return AssistantReply(
            "Current cost assumptions:\n"
            f"- Brokerage: {c.brokerage_pct}% (min ₹{c.brokerage_min_inr})\n"
            f"- STT buy/sell: {c.stt_buy_pct}% / {c.stt_sell_pct}%\n"
            f"- GST: {c.gst_pct}%, stamp duty (buy): {c.stamp_duty_buy_pct}%\n"
            f"- Slippage: {c.slippage_pct}%\n"
            f"- Config verified: {c.config_verified_date}" + warn,
            data={"verified": verified},
        )

    def _status(self) -> AssistantReply:
        signals = self.conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]
        positions = self.conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE qty != 0"
        ).fetchone()["c"]
        watch = self.conn.execute("SELECT COUNT(*) c FROM watchlist").fetchone()["c"]
        return AssistantReply(
            "Status:\n"
            f"- Watchlist: {watch} symbols\n"
            f"- Signals computed: {signals}\n"
            f"- Open positions: {positions}\n"
            f"- Live trading: DISABLED (by design)\n"
            f"- Assistant provider: local rules only (no external calls)",
            data={"signals": signals, "positions": positions, "watchlist": watch},
        )

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_symbol(original: str) -> str | None:
        # Only treat ALL-CAPS tokens in the original question as ticker symbols.
        skip = {"AI", "API", "CSV", "NSE", "BSE", "SMA", "RSI", "ATR", "OHLC", "ETF", "IPO"}
        for tok in re.findall(r"\b[A-Z]{2,10}\b", original):
            if tok not in skip:
                return tok
        return None

    def _symbol_question(self, symbol: str, q: str) -> AssistantReply:
        inst = self.conn.execute(
            "SELECT id FROM instruments WHERE symbol = ?", (symbol,)
        ).fetchone()
        if not inst:
            return AssistantReply(
                f"{symbol} is not in your instruments. Add it to the watchlist first."
            )
        sig = self.conn.execute(
            "SELECT action, details_json FROM signals "
            "WHERE instrument_id = ? ORDER BY id DESC LIMIT 1",
            (inst["id"],),
        ).fetchone()
        pos = self.conn.execute(
            "SELECT qty, avg_cost FROM positions WHERE instrument_id = ? AND qty != 0",
            (inst["id"],),
        ).fetchone()
        parts = [f"{symbol}:"]
        if sig:
            parts.append(f"latest signal = {sig['action']} ({(sig['details_json'] or '')[:60]})")
        else:
            parts.append("no signal computed")
        if pos:
            parts.append(f"position = {pos['qty']} @ ₹{pos['avg_cost']:.2f}")
        else:
            parts.append("no open position")
        return AssistantReply(" | ".join(parts), data={"symbol": symbol})
