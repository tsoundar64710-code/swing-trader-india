"""Flask web application for Swing Trader India.

Binds to 127.0.0.1 only. No live trading. All paper/simulated.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from flask import Flask

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from swingtrader.core.logging_setup import setup_logging  # noqa: E402
from swingtrader.core.settings import DATA_DIR, DB_PATH, load_settings  # noqa: E402
from swingtrader.db.database import init_database  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "swingtrader-local-only"  # noqa: S105 # no remote sessions
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

    setup_logging(DATA_DIR / "logs")
    settings = load_settings()
    conn = init_database(DB_PATH)
    conn.row_factory = sqlite3.Row

    app.config["SETTINGS"] = settings
    app.config["DB"] = conn

    from swingtrader.web.routes import bp as main_bp

    app.register_blueprint(main_bp)
    return app
