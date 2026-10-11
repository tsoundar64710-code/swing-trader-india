"""All Flask routes: HTML pages + JSON API endpoints."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)

from swingtrader import LIVE_TRADING_ENABLED, OPERATING_MODE, __version__
from swingtrader.backtest.engine import run_backtest, run_split_backtest, run_walk_forward
from swingtrader.backtest.persistence import save_backtest_run
from swingtrader.core.errors import DataValidationError, OrderError, SettingsError
from swingtrader.core.settings import save_settings
from swingtrader.costs.engine import cost_warning
from swingtrader.data.loader import load_ohlcv_csv
from swingtrader.data.store import (
    add_to_watchlist,
    export_watchlist_csv,
    find_instrument,
    get_or_create_instrument,
    list_imports,
    list_watchlist,
    load_candles,
    remove_from_watchlist,
    save_import,
)
from swingtrader.data.validator import validate_ohlcv
from swingtrader.paper.engine import PaperEngine
from swingtrader.risk.sizing import PortfolioState, size_position
from swingtrader.strategies.persistence import save_signal
from swingtrader.strategies.signals import trend_pullback_signal

bp = Blueprint("main", __name__)


def _ctx(**extra):
    s = current_app.config["SETTINGS"]
    conn = current_app.config["DB"]
    return dict(
        version=__version__,
        operating_mode=OPERATING_MODE,
        live_trading=LIVE_TRADING_ENABLED,
        settings=s,
        cost_warning=cost_warning(s.costs),
        watchlist=list_watchlist(conn),
        **extra,
    )


# ────────────────────────────────────────────── pages


@bp.get("/")
def dashboard():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    positions = engine.positions()
    prices = {}
    for p in positions:
        row = find_instrument(conn, p["symbol"])
        if row:
            df = load_candles(conn, row["id"])
            if len(df):
                prices[p["symbol"]] = float(df["close"].iloc[-1])
    equity = engine.equity(prices)
    recent_imports = list_imports(conn, limit=5)
    n_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    return render_template(
        "dashboard.html", **_ctx(
            cash=engine.cash(), equity=equity, positions=positions, prices=prices,
            realized_pnl=engine.realized_pnl_total(), n_positions=len(positions),
            recent_imports=recent_imports, n_signals=n_signals,
        ),
    )


@bp.get("/watchlist")
def watchlist_page():
    return render_template("watchlist.html", **_ctx())


@bp.get("/research/<symbol>")
def research_page(symbol: str):
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    inst = find_instrument(conn, symbol)
    if not inst:
        return render_template("watchlist.html", **_ctx(error=f"Symbol {symbol} not found."))
    df = load_candles(conn, inst["id"])
    sig = None
    ind_tail = []
    plan = None
    if len(df):
        sig = trend_pullback_signal(symbol, df, s.strategy)
        save_signal(conn, inst["id"], sig)
        from swingtrader.strategies.indicators import add_indicators
        ind = add_indicators(df, s.strategy)
        ind_tail = json.loads(ind.tail(30).to_json(orient="records", date_format="iso"))
        if sig.action == "BUY_SETUP" and sig.entry_reference and sig.stop_price:
            portfolio = PortfolioState(
                equity_inr=s.initial_capital_inr, cash_inr=s.initial_capital_inr,
                open_positions=0, exposure_inr=0.0,
            )
            plan = size_position(sig.entry_reference, sig.stop_price, portfolio, s)
    candles = json.loads(df.to_json(orient="records", date_format="iso")) if len(df) else []
    return render_template(
        "research.html", **_ctx(
            symbol=symbol, inst=inst, candles=candles, sig=sig,
            ind_tail=ind_tail, plan=plan,
        ),
    )


@bp.get("/signals")
def signals_page():
    return render_template("signals.html", **_ctx())


@bp.get("/strategy-lab")
def strategy_lab_page():
    return render_template("strategy_lab.html", **_ctx())


@bp.get("/paper")
def paper_page():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    positions = engine.positions()
    prices = {}
    for p in positions:
        row = find_instrument(conn, p["symbol"])
        if row:
            df = load_candles(conn, row["id"])
            if len(df):
                prices[p["symbol"]] = float(df["close"].iloc[-1])
    recon = engine.reconcile()
    return render_template(
        "paper.html", **_ctx(
            cash=engine.cash(), equity=engine.equity(prices), positions=positions,
            prices=prices, orders=engine.orders(), realized_pnl=engine.realized_pnl_total(),
            recon=recon,
        ),
    )


@bp.get("/data")
def data_page():
    conn = current_app.config["DB"]
    return render_template("data.html", **_ctx(imports=list_imports(conn)))


@bp.get("/settings")
def settings_page():
    return render_template("settings.html", **_ctx())


@bp.get("/portfolio")
def portfolio_page():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    positions = engine.positions()
    cash = engine.cash()
    rows = []
    invested = 0.0
    for p in positions:
        inst = find_instrument(conn, p["symbol"])
        last = None
        if inst:
            df = load_candles(conn, inst["id"])
            if len(df):
                last = float(df["close"].iloc[-1])
        mv = (last or p["avg_cost"]) * p["qty"]
        upnl = (last - p["avg_cost"]) * p["qty"] if last else 0.0
        invested += mv
        rows.append({
            "symbol": p["symbol"], "qty": p["qty"], "avg_cost": p["avg_cost"],
            "last": last, "mv": round(mv, 2), "upnl": round(upnl, 2),
            "pct": round(100 * mv / (cash + invested + 1e-9), 1) if (cash + invested) else 0,
            "stop_risk": (
                round((p["avg_cost"] - p["stop_price"]) * p["qty"], 2) if p["stop_price"] else None
            ),
        })
    equity = cash + invested
    exposure_pct = round(100 * invested / equity, 1) if equity else 0
    breaches = []
    if exposure_pct > s.risk.max_portfolio_exposure_pct:
        breaches.append(
            f"Portfolio exposure {exposure_pct}% exceeds limit {s.risk.max_portfolio_exposure_pct}%"
        )
    for r in rows:
        if r["pct"] > s.risk.max_position_pct:
            breaches.append(
                f"{r['symbol']} is {r['pct']}% of equity (limit {s.risk.max_position_pct}%)"
            )
    if len(rows) > s.risk.max_open_positions:
        breaches.append(f"Open positions {len(rows)} exceeds limit {s.risk.max_open_positions}")
    for r in rows:
        if r["stop_risk"] is None:
            breaches.append(f"{r['symbol']} has no stop-loss set")
    recon = engine.reconcile()
    return render_template("portfolio.html", **_ctx(
        positions=rows, cash=cash, equity=round(equity, 2), invested=round(invested, 2),
        exposure_pct=exposure_pct, breaches=breaches, recon=recon,
    ))


@bp.get("/journal")
def journal_page():
    conn = current_app.config["DB"]
    entries = [dict(r) for r in conn.execute(
        "SELECT * FROM journal_entries ORDER BY id DESC LIMIT 100"
    ).fetchall()]
    return render_template("journal.html", **_ctx(entries=entries))


# ────────────────────────────────────────────── API: watchlist


@bp.post("/api/watchlist/add")
def api_watchlist_add():
    conn = current_app.config["DB"]
    data = request.get_json(force=True)
    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "NSE").strip()
    if not symbol:
        return jsonify({"ok": False, "error": "Symbol required."}), 400
    try:
        inst = find_instrument(conn, symbol, exchange)
        iid = inst["id"] if inst else get_or_create_instrument(conn, symbol, exchange)
        add_to_watchlist(conn, iid)
        has_data = bool(load_candles(conn, iid).shape[0])
        return jsonify({"ok": True, "symbol": symbol.upper(), "has_data": has_data})
    except DataValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.post("/api/watchlist/remove")
def api_watchlist_remove():
    conn = current_app.config["DB"]
    data = request.get_json(force=True)
    inst = find_instrument(conn, data.get("symbol", ""), data.get("exchange", "NSE"))
    if inst:
        remove_from_watchlist(conn, inst["id"])
    return jsonify({"ok": True})


@bp.get("/api/watchlist/export")
def api_watchlist_export():
    conn = current_app.config["DB"]
    from swingtrader.core.settings import DATA_DIR
    out = DATA_DIR / "exports" / "watchlist.csv"
    export_watchlist_csv(conn, out)
    return send_file(out, as_attachment=True, download_name="watchlist.csv")


@bp.get("/api/watchlist")
def api_watchlist():
    return jsonify({"ok": True, "items": list_watchlist(current_app.config["DB"])})


# ────────────────────────────────────────────── API: signals


@bp.get("/api/signals")
def api_signals():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    from datetime import datetime as dt

    out = []
    for row in list_watchlist(conn):
        df = load_candles(conn, row["id"])
        if not len(df):
            out.append({
                "symbol": row["symbol"], "exchange": row["exchange"],
                "action": "NO_TRADE", "data_ts": "—", "entry": None,
                "stop": None, "target": None, "rr": None, "reason": "No data imported",
            })
            continue
        last_ts = str(df["ts"].iloc[-1])
        try:
            age = (dt.now() - dt.fromisoformat(last_ts)).days
            stale = age > s.data.stale_after_days
        except ValueError:
            stale = True
        sig = trend_pullback_signal(row["symbol"], df, s.strategy, stale=stale)
        save_signal(conn, row["id"], sig)
        out.append({
            "symbol": row["symbol"], "exchange": row["exchange"],
            "action": sig.action, "data_ts": sig.data_ts,
            "entry": sig.entry_reference, "stop": sig.stop_price,
            "target": sig.target_price, "rr": sig.reward_risk,
            "reason": "; ".join(sig.reasons[:2]),
            "rules_ok": sig.rules_satisfied, "rules_fail": sig.rules_failed,
        })
    return jsonify({"ok": True, "signals": out})


# ────────────────────────────────────────────── API: backtest


@bp.post("/api/backtest/run")
def api_backtest_run():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    data = request.get_json(force=True)
    symbol = data.get("symbol", "")
    mode = data.get("mode", "full")
    capital = float(data.get("capital", s.initial_capital_inr))
    inst = find_instrument(conn, symbol)
    if not inst:
        return jsonify({"ok": False, "error": f"Unknown symbol {symbol}"}), 400
    df = load_candles(conn, inst["id"])
    if len(df) < 60:
        return jsonify({"ok": False, "error": "Need at least 60 candles."}), 400

    scopy = copy.deepcopy(s)
    scopy.strategy.sma_fast = int(data.get("sma_fast", s.strategy.sma_fast))
    scopy.strategy.sma_slow = int(data.get("sma_slow", s.strategy.sma_slow))
    scopy.strategy.atr_stop_multiplier = float(
        data.get("atr_mult", s.strategy.atr_stop_multiplier)
    )
    scopy.strategy.min_reward_risk = float(
        data.get("min_rr", s.strategy.min_reward_risk)
    )
    if scopy.strategy.sma_slow <= scopy.strategy.sma_fast:
        return jsonify({"ok": False, "error": "Slow SMA must exceed fast SMA."}), 400

    if mode == "splits":
        results = run_split_backtest(df, scopy, initial_capital=capital)
    elif mode == "walk_forward":
        results = {"walk_forward": run_walk_forward(df, scopy, initial_capital=capital)}
    else:
        results = {"full": run_backtest(df, scopy, initial_capital=capital, symbol=symbol)}

    payload = {}
    for name, r in results.items():
        r.config["symbol"] = symbol
        run_id = save_backtest_run(conn, r)
        payload[name] = {
            "run_id": run_id,
            "metrics": r.metrics,
            "trades": r.trades[-50:],
            "equity_curve": r.equity_curve,
            "dates": r.dates,
            "config": r.config,
            "warnings": r.warnings,
        }
    return jsonify({"ok": True, "results": payload})


# ────────────────────────────────────────────── API: paper trading


@bp.post("/api/paper/order")
def api_paper_order():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    data = request.get_json(force=True)
    try:
        r = engine.place_market_order(
            data["symbol"].upper(), data["side"], int(data["qty"]),
            ref_price=float(data["ref_price"]), notes=data.get("notes"),
        )
        return jsonify(r)
    except (OrderError, KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.post("/api/paper/close/<symbol>")
def api_paper_close(symbol: str):
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    inst = find_instrument(conn, symbol)
    if not inst:
        return jsonify({"ok": False, "error": "Unknown symbol"}), 400
    df = load_candles(conn, inst["id"])
    if not len(df):
        return jsonify({"ok": False, "error": "No price data"}), 400
    try:
        r = engine.close_position(symbol, float(df["close"].iloc[-1]), reason="manual")
        return jsonify(r)
    except OrderError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.post("/api/paper/monitor")
def api_paper_monitor():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    engine = PaperEngine(conn, s)
    bars = {}
    for p in engine.positions():
        inst = find_instrument(conn, p["symbol"])
        if not inst:
            continue
        df = load_candles(conn, inst["id"])
        if len(df):
            r = df.iloc[-1]
            bars[p["symbol"]] = {
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            }
    exits = engine.check_stop_target_exits(bars)
    return jsonify({"ok": True, "exits": exits})


@bp.post("/api/paper/stop_target")
def api_paper_stop_target():
    conn = current_app.config["DB"]
    data = request.get_json(force=True)
    conn.execute(
        "UPDATE positions SET stop_price=?, target_price=? WHERE symbol=?",
        (data.get("stop") or None, data.get("target") or None, data["symbol"]),
    )
    conn.commit()
    return jsonify({"ok": True})


# ────────────────────────────────────────────── API: data import


@bp.post("/data/import")
def api_data_import():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    symbol = (request.form.get("symbol") or "").strip().upper()
    exchange = request.form.get("exchange", "NSE")
    adjusted = request.form.get("adjusted", "unknown")
    file = request.files.get("file")
    if not file or not symbol:
        return render_template("data.html", **_ctx(
            imports=list_imports(conn), error="Symbol and file are required.",
        ))
    try:
        raw = file.read()
        raw_df = load_ohlcv_csv(
            raw, max_mb=s.data.max_import_file_mb, max_rows=s.data.max_import_rows,
        )
        clean, rep = validate_ohlcv(raw_df, stale_after_days=s.data.stale_after_days)
        if not rep.ok or not len(clean):
            return render_template("data.html", **_ctx(
                imports=list_imports(conn), report=rep,
                error="Import blocked: dataset failed validation.",
            ))
        iid = get_or_create_instrument(conn, symbol, exchange)
        save_import(
            conn, iid, clean, rep, timezone_name=s.data.timezone,
            source_name=file.filename or "upload.csv", source_type="csv", adjusted=adjusted,
        )
        return render_template("data.html", **_ctx(
            imports=list_imports(conn), report=rep,
            success=f"Imported {rep.valid_rows:,} candles for {symbol}.",
        ))
    except DataValidationError as e:
        return render_template("data.html", **_ctx(
            imports=list_imports(conn), error=str(e),
        ))


# ────────────────────────────────────────────── API: settings


@bp.post("/api/settings")
def api_settings():
    s = current_app.config["SETTINGS"]
    data = request.get_json(force=True)
    try:
        s.initial_capital_inr = float(data.get("initial_capital_inr", s.initial_capital_inr))
        s.risk.max_position_pct = float(data.get("max_position_pct", s.risk.max_position_pct))
        s.risk.max_risk_per_trade_pct = float(
            data.get("max_risk_per_trade_pct", s.risk.max_risk_per_trade_pct)
        )
        s.risk.max_open_positions = int(data.get("max_open_positions", s.risk.max_open_positions))
        s.risk.max_portfolio_exposure_pct = float(
            data.get("max_portfolio_exposure_pct", s.risk.max_portfolio_exposure_pct)
        )
        s.strategy.sma_fast = int(data.get("sma_fast", s.strategy.sma_fast))
        s.strategy.sma_slow = int(data.get("sma_slow", s.strategy.sma_slow))
        s.strategy.atr_stop_multiplier = float(
            data.get("atr_stop_multiplier", s.strategy.atr_stop_multiplier)
        )
        s.strategy.min_reward_risk = float(data.get("min_reward_risk", s.strategy.min_reward_risk))
        save_settings(s)
        return jsonify({"ok": True})
    except (ValueError, TypeError, SettingsError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ────────────────────────────────────────────── API: journal


@bp.post("/api/journal/add")
def api_journal_add():
    conn = current_app.config["DB"]
    data = request.get_json(force=True)
    symbol = (data.get("symbol") or "").strip().upper() or None
    iid = None
    if symbol:
        inst = find_instrument(conn, symbol)
        iid = inst["id"] if inst else None
    with conn:
        conn.execute(
            """INSERT INTO journal_entries
               (instrument_id, trade_ref, created_at, entry_rationale, planned_exit,
                actual_exit, outcome, rule_violations, lessons)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                iid, data.get("trade_ref") or None, datetime.now(UTC).isoformat(),
                data.get("entry_rationale") or None, data.get("planned_exit") or None,
                data.get("actual_exit") or None, data.get("outcome") or None,
                data.get("rule_violations") or None, data.get("lessons") or None,
            ),
        )
    return jsonify({"ok": True})


@bp.get("/api/journal")
def api_journal():
    conn = current_app.config["DB"]
    entries = [dict(r) for r in conn.execute(
        "SELECT * FROM journal_entries ORDER BY id DESC LIMIT 100"
    ).fetchall()]
    return jsonify({"ok": True, "entries": entries})


# ────────────────────────────────────────────── API: assistant


@bp.get("/assistant")
def assistant_page():
    s = current_app.config["SETTINGS"]
    return render_template("assistant.html", **_ctx(enabled=s.ai.enabled))


@bp.post("/api/assistant/chat")
def api_assistant_chat():
    s = current_app.config["SETTINGS"]
    if not s.ai.enabled:
        return jsonify({
            "ok": False,
            "error": "Assistant is disabled. Enable it on the Assistant page.",
        }), 403
    conn = current_app.config["DB"]
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "Question is empty."}), 400
    from swingtrader.ai import Assistant
    reply = Assistant(conn, s).answer(question)
    return jsonify({
        "ok": True,
        "answer": reply.answer,
        "refused": reply.refused,
        "data": reply.data,
    })


@bp.post("/api/assistant/enable")
def api_assistant_enable():
    s = current_app.config["SETTINGS"]
    data = request.get_json(force=True) or {}
    enabled = data.get("enabled", True)
    s.ai.enabled = bool(enabled)
    save_settings(s)
    return jsonify({"ok": True, "enabled": s.ai.enabled})


# ────────────────────────────────────────────── API: health


@bp.get("/api/health")
def api_health():
    return jsonify({
        "ok": True, "version": __version__, "mode": OPERATING_MODE,
        "live_trading": LIVE_TRADING_ENABLED, "ts": datetime.now(UTC).isoformat(),
    })
