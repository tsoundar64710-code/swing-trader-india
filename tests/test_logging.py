"""Logging redaction tests."""

from __future__ import annotations

import logging

from swingtrader.core.logging_setup import RedactionFilter, setup_logging


def _capture(record: logging.LogRecord) -> str:
    f = RedactionFilter()
    assert f.filter(record)
    return record.getMessage()


def test_api_key_redacted() -> None:
    msg = "using api_key=sk-abc123XYZ"
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)
    assert "sk-abc123XYZ" not in _capture(rec)
    assert "[REDACTED]" in _capture(rec)


def test_password_redacted() -> None:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "password=hunter2", None, None)
    assert "hunter2" not in _capture(rec)


def test_normal_message_untouched() -> None:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "Loaded 42 candles", None, None)
    assert _capture(rec) == "Loaded 42 candles"


def test_setup_logging_idempotent(tmp_path) -> None:
    a = setup_logging(tmp_path / "logs")
    b = setup_logging(tmp_path / "logs")
    assert a is b
