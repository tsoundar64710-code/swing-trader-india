"""Flask web application for Swing Trader India.

Binds to 127.0.0.1 only. No live trading. All paper/simulated.
"""

from __future__ import annotations

import secrets
import sqlite3
import sys
from pathlib import Path

from flask import Flask, session

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from swingtrader.core.logging_setup import setup_logging  # noqa: E402
from swingtrader.core.settings import DATA_DIR, DB_PATH, load_settings  # noqa: E402
from swingtrader.db.database import init_database  # noqa: E402


def _load_or_create_secret() -> str:
    """Load a random session secret from data/.secret_key, creating it if missing."""
    key_path = DATA_DIR / ".secret_key"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key, encoding="utf-8")
    return key


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = _load_or_create_secret()
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

    setup_logging(DATA_DIR / "logs")
    settings = load_settings()
    conn = init_database(DB_PATH)
    conn.row_factory = sqlite3.Row

    app.config["SETTINGS"] = settings
    app.config["DB"] = conn

    from swingtrader.web.routes import bp as main_bp

    app.register_blueprint(main_bp)

    @app.before_request
    def _ensure_csrf_token() -> None:
        """Ensure a CSRF token exists in the session for state-changing requests."""
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)

    @app.context_processor
    def _inject_csrf() -> dict:
        """Inject CSRF token into templates for form/fetch use."""
        return {"csrf_token": session.get("csrf_token", "")}

    return app
