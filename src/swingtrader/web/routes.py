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


# ────────────────────────────────────────────── Market dashboard


@bp.get("/market")
def market_page():
    return render_template("market.html", **_ctx())


@bp.get("/api/market/status")
def api_market_status():
    from swingtrader.market.provider import market_status
    return jsonify({"ok": True, **market_status().to_dict()})


@bp.get("/api/market/indices")
def api_market_indices():
    from swingtrader.market.provider import fetch_indices
    qs = fetch_indices()
    return jsonify({"ok": True, "quotes": [q.to_dict() for q in qs]})


@bp.get("/api/market/macro")
def api_market_macro():
    from swingtrader.market.provider import fetch_macro
    qs = fetch_macro()
    return jsonify({"ok": True, "quotes": [q.to_dict() for q in qs]})


@bp.get("/api/market/quote/<symbol>")
def api_market_quote(symbol: str):
    from swingtrader.market.provider import fetch_quote
    q = fetch_quote(symbol)
    return jsonify({"ok": True, "quote": q.to_dict()})


@bp.get("/api/market/breadth")
def api_market_breadth():
    from swingtrader.market.provider import fetch_quotes, market_breadth
    conn = current_app.config["DB"]
    rows = list_watchlist(conn)
    symbols = [r["symbol"] for r in rows][:30]
    if not symbols:
        return jsonify({"ok": False, "error": "Watchlist empty — add symbols first."}), 400
    qs = fetch_quotes(symbols)
    return jsonify({"ok": True, "breadth": market_breadth(qs),
                    "quotes": [q.to_dict() for q in qs]})


# ────────────────────────────────────────────── Scanner


@bp.get("/scanner")
def scanner_page():
    return render_template("scanner.html", **_ctx())


@bp.post("/api/scanner/run")
def api_scanner_run():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    from swingtrader.market.provider import SECTOR_MAP, fetch_quote
    from swingtrader.market.scanner import rank_stocks, scan_stock

    data = request.get_json(force=True) or {}
    symbols = data.get("symbols") or []
    if not symbols:
        rows = list_watchlist(conn)
        symbols = [r["symbol"] for r in rows][:20]
    if not symbols:
        return jsonify({"ok": False, "error": "No symbols to scan."}), 400

    # Benchmark: Nifty 1-month change for relative strength
    bench = fetch_quote("^NSEI")
    bench_1m = None
    if bench.price and bench.prev_close:
        bench_1m = bench.change_pct

    results = []
    for sym in symbols:
        inst_id = get_or_create_instrument(conn, sym, "NSE", sym)
        df = load_candles(conn, inst_id)
        if len(df) < 60:
            # try fetching history from provider and upsert directly
            from swingtrader.market.provider import fetch_history
            rows, err = fetch_history(sym, period="1y")
            if rows:
                with conn:
                    conn.executemany(
                        """INSERT INTO candles(instrument_id, ts, open, high, low, close, volume)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(instrument_id, ts) DO UPDATE SET
                             open=excluded.open, high=excluded.high, low=excluded.low,
                             close=excluded.close, volume=excluded.volume""",
                        [(inst_id, r["ts"], r["open"], r["high"], r["low"],
                          r["close"], r["volume"]) for r in rows],
                    )
                df = load_candles(conn, inst_id)
        sector = SECTOR_MAP.get(sym.upper(), "Other")
        r = scan_stock(sym, df, s.strategy, sector=sector,
                       benchmark_change_pct=bench_1m)
        results.append(r)

    ranked = rank_stocks(results)
    return jsonify({"ok": True, "results": [r.to_dict() for r in ranked]})


# ────────────────────────────────────────────── News


@bp.get("/news")
def news_page():
    return render_template("news.html", **_ctx())


@bp.get("/api/news")
def api_news():
    symbol = request.args.get("symbol")
    from swingtrader.market.news import dedupe_news, fetch_yahoo_news
    items = fetch_yahoo_news(symbol)
    items = dedupe_news(items)
    return jsonify({"ok": True, "items": [i.to_dict() for i in items],
                    "count": len(items)})


# ────────────────────────────────────────────── Trade planner


@bp.get("/planner")
def planner_page():
    return render_template("planner.html", **_ctx())


@bp.post("/api/planner/build")
def api_planner_build():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    from swingtrader.market.planner import build_trade_plan
    from swingtrader.market.provider import fetch_quote
    from swingtrader.paper.engine import PaperEngine
    from swingtrader.risk.sizing import PortfolioState

    data = request.get_json(force=True)
    symbol = (data.get("symbol") or "").strip().upper()
    entry = float(data.get("entry", 0))
    stop = float(data.get("stop", 0))
    target = data.get("target")
    target = float(target) if target else None
    rationale = data.get("rationale", "")

    if not symbol or entry <= 0 or stop <= 0:
        return jsonify({"ok": False, "error": "symbol, entry and stop are required."}), 400

    engine = PaperEngine(conn, s)
    cash = engine.cash()
    positions = engine.positions()
    exposure = sum(p["avg_cost"] * p["qty"] for p in positions)
    pf = PortfolioState(
        equity_inr=cash + exposure, cash_inr=cash,
        open_positions=len(positions), exposure_inr=exposure,
    )

    q = fetch_quote(symbol)
    plan = build_trade_plan(
        symbol, latest_price=q.price, price_timestamp=q.timestamp,
        price_quality=q.quality, price_source=q.source,
        entry_reference=entry, stop_price=stop, target_price=target,
        rationale=rationale, portfolio=pf, settings=s,
    )
    return jsonify({"ok": True, "plan": plan.to_dict()})


# ────────────────────────────────────────────── Alerts & notifications


@bp.get("/alerts")
def alerts_page():
    return render_template("alerts.html", **_ctx())


@bp.post("/api/alerts/check")
def api_alerts_check():
    conn = current_app.config["DB"]
    s = current_app.config["SETTINGS"]
    from swingtrader.market.alerts import AlertEngine
    from swingtrader.market.provider import fetch_quotes
    from swingtrader.strategies.indicators import add_indicators

    engine = AlertEngine()
    rows = list_watchlist(conn)
    symbols = [r["symbol"] for r in rows][:20]
    if not symbols:
        return jsonify({"ok": False, "error": "Watchlist empty."}), 400

    quotes = {q.symbol.upper(): q for q in fetch_quotes(symbols)}
    all_alerts = []
    for row in rows:
        sym = row["symbol"]
        q = quotes.get(sym.upper())
        if not q or q.price is None:
            continue
        # Load candles for support/resistance/volume context
        inst = find_instrument(conn, sym)
        support = resistance = avg_vol = None
        if inst:
            df = load_candles(conn, inst["id"])
            if len(df) >= 20:
                from swingtrader.core.settings import StrategySettings
                ind = add_indicators(df, StrategySettings())
                support = float(ind["low"].tail(20).min())
                resistance = float(ind["high"].tail(20).max())
                avg_vol = float(ind["volume"].tail(20).mean())
        age_h = None
        if q.timestamp:
            try:
                from datetime import datetime as _dt
                age_h = (_dt.now(UTC) - _dt.fromisoformat(q.timestamp)).total_seconds() / 3600
            except ValueError:
                pass
        alerts = engine.check_symbol(
            sym, price=q.price, volume=q.volume, avg_volume=avg_vol,
            prev_close=q.prev_close, support=support, resistance=resistance,
            data_age_hours=age_h, stale_after_days=s.data.stale_after_days,
        )
        all_alerts.extend(alerts)

    # Also check open paper positions for stop/target proximity
    from swingtrader.paper.engine import PaperEngine
    paper = PaperEngine(conn, s)
    for p in paper.positions():
        q = quotes.get(p["symbol"].upper())
        if q and q.price:
            stop_alerts = engine.check_symbol(
                p["symbol"], price=q.price,
                stop=p["stop_price"], target=p["target_price"],
            )
            all_alerts.extend(stop_alerts)

    return jsonify({"ok": True, "alerts": [a.to_dict() for a in all_alerts]})


@bp.get("/api/notifications")
def api_notifications():
    from swingtrader.market.notify import NotificationCenter
    conn = current_app.config["DB"]
    nc = NotificationCenter(conn)
    return jsonify({"ok": True, "items": nc.history(100)})


@bp.post("/api/notifications/prefs")
def api_notification_prefs():
    from swingtrader.market.notify import NotificationPrefs
    s = current_app.config["SETTINGS"]
    data = request.get_json(force=True) or {}
    # Store in settings.ai-adjacent slot via simple attributes on settings
    if not hasattr(s, "notify"):
        s.notify = NotificationPrefs()
    if "desktop_toast" in data:
        s.notify.desktop_toast = bool(data["desktop_toast"])
    if "quiet_hours_start" in data:
        s.notify.quiet_hours_start = str(data["quiet_hours_start"])
    if "quiet_hours_end" in data:
        s.notify.quiet_hours_end = str(data["quiet_hours_end"])
    if "min_severity" in data:
        s.notify.min_severity = str(data["min_severity"]).upper()
    save_settings(s)
    return jsonify({"ok": True, "prefs": {
        "desktop_toast": s.notify.desktop_toast,
        "quiet_hours_start": s.notify.quiet_hours_start,
        "quiet_hours_end": s.notify.quiet_hours_end,
        "min_severity": s.notify.min_severity,
    }})


# ────────────────────────────────────────────── API: health


@bp.get("/api/health")
def api_health():
    return jsonify({
        "ok": True, "version": __version__, "mode": OPERATING_MODE,
        "live_trading": LIVE_TRADING_ENABLED, "ts": datetime.now(UTC).isoformat(),
    })
