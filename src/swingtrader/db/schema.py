"""SQLite schema and ordered migrations."""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS instruments (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'NSE',
            name TEXT,
            sector TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(symbol, exchange)
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL,
            UNIQUE(instrument_id)
        );

        CREATE TABLE IF NOT EXISTS data_sources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candle_imports (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES instruments(id),
            source_id INTEGER REFERENCES data_sources(id),
            interval TEXT NOT NULL,
            timezone TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            date_start TEXT,
            date_end TEXT,
            adjusted TEXT NOT NULL DEFAULT 'unknown',
            validation_status TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS candles (
            instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
            ts TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 0,
            import_id INTEGER REFERENCES candle_imports(id),
            PRIMARY KEY (instrument_id, ts)
        );
        CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles(instrument_id, ts);

        CREATE TABLE IF NOT EXISTS strategy_configs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            params_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(name, version)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES instruments(id),
            strategy_id INTEGER REFERENCES strategy_configs(id),
            signal_ts TEXT NOT NULL,
            data_ts TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('BUY_SETUP','WAIT','SELL_EXIT_SETUP','NO_TRADE')),
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY,
            strategy_id INTEGER REFERENCES strategy_configs(id),
            config_json TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            split TEXT NOT NULL DEFAULT 'full',
            status TEXT NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS backtest_trades (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            entry_ts TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_ts TEXT,
            exit_price REAL,
            qty INTEGER NOT NULL,
            costs REAL NOT NULL DEFAULT 0,
            pnl REAL NOT NULL DEFAULT 0,
            exit_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            client_order_id TEXT NOT NULL UNIQUE,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
            qty INTEGER NOT NULL CHECK(qty > 0),
            order_type TEXT NOT NULL DEFAULT 'MARKET',
            limit_price REAL,
            status TEXT NOT NULL CHECK(status IN ('PENDING','FILLED','CANCELLED','REJECTED')),
            reason TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            ts TEXT NOT NULL,
            price REAL NOT NULL,
            qty INTEGER NOT NULL,
            brokerage REAL NOT NULL DEFAULT 0,
            taxes_fees REAL NOT NULL DEFAULT 0,
            slippage REAL NOT NULL DEFAULT 0,
            pnl_realized REAL
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            qty INTEGER NOT NULL CHECK(qty >= 0),
            avg_cost REAL NOT NULL,
            stop_price REAL,
            target_price REAL,
            opened_at TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS cash_ledger (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            amount REAL NOT NULL,
            kind TEXT NOT NULL,
            ref_id INTEGER,
            balance_after REAL NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER REFERENCES instruments(id),
            trade_ref TEXT,
            created_at TEXT NOT NULL,
            entry_rationale TEXT,
            planned_exit TEXT,
            actual_exit TEXT,
            outcome TEXT,
            rule_violations TEXT,
            lessons TEXT,
            chart_ref TEXT
        );

        CREATE TABLE IF NOT EXISTS cost_config (
            id INTEGER PRIMARY KEY,
            effective_date TEXT NOT NULL,
            config_json TEXT NOT NULL,
            source_note TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            event TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
    ),
]
