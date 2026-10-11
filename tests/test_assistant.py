"""Tests for the rule-based local assistant (Phase 8)."""

from __future__ import annotations

import pytest

from swingtrader.ai import Assistant
from swingtrader.core.settings import AppSettings
from swingtrader.db.database import init_database


@pytest.fixture
def conn(tmp_path):
    c = init_database(tmp_path / "t.db")
    yield c
    c.close()


def test_disabled_by_default():
    s = AppSettings()
    assert s.ai.enabled is False
    assert s.ai.provider == "local_rules"


def test_answer_requires_data(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("What is my cash?")
    assert r.ok if hasattr(r, "ok") else "₹" in r.answer
    assert "cash" in r.answer.lower() or "balance" in r.answer.lower()


def test_refuses_advice(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("Should I buy TCS tomorrow?")
    assert r.refused is True
    assert "advice" in r.answer.lower()


def test_greeting(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("hello")
    assert "hello" in r.answer.lower() or "hi" in r.answer.lower()


def test_help(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("help")
    assert "watchlist" in r.answer.lower() or "signals" in r.answer.lower()


def test_strategy_question(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("Explain the strategy")
    assert "sma" in r.answer.lower() or "strategy" in r.answer.lower()


def test_risk_limits(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("What are my risk limits?")
    assert "max" in r.answer.lower() or "position" in r.answer.lower()


def test_costs_question(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("What are transaction costs?")
    assert "brokerage" in r.answer.lower() or "slippage" in r.answer.lower()
    assert "UNVERIFIED" in r.answer  # must warn about unverified rates


def test_status(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("Status overview")
    assert "watchlist" in r.answer.lower() or "signal" in r.answer.lower()


def test_empty_question(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("   ")
    assert len(r.answer) > 0


def test_unknown_question(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("quantum flux capacitor timing")
    assert "could not match" in r.answer.lower() or "try" in r.answer.lower()


def test_watchlist_empty(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("List my watchlist")
    assert "empty" in r.answer.lower() or "watching" in r.answer.lower()


def test_positions_empty(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("Show my positions")
    assert "position" in r.answer.lower()


def test_journal_empty(conn):
    a = Assistant(conn, AppSettings())
    r = a.answer("Show my journal")
    assert "journal" in r.answer.lower()
