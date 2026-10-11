"""Structured logging with sensitive-value redaction."""

from __future__ import annotations

import logging
import re
from pathlib import Path

_SENSITIVE_KEYS = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|password|passwd|token|otp|secret|authorization)"
    r"(\s*[=:]\s*)(\S+)"
)


class RedactionFilter(logging.Filter):
    """Scrub obvious secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging break the app
            return True
        redacted = _SENSITIVE_KEYS.sub(r"\1\2[REDACTED]", msg)
        if "[REDACTED]" not in redacted:
            redacted = re.sub(
                r"(?i)\b(sk|key|token|secret)[-_][A-Za-z0-9]{8,}",
                "[REDACTED]",
                redacted,
            )
        record.msg = redacted
        record.args = ()
        return True


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the root app logger: console + rotating file, redacted."""
    logger = logging.getLogger("swingtrader")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    red = RedactionFilter()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(red)
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(red)
        logger.addHandler(fh)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"swingtrader.{name}")
