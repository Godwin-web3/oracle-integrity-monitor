"""
Flask application — multi-chain oracle integrity dashboard.
Runs alongside the Telegram bot and background price monitor.
"""
import os
import json
import asyncio
import logging
import threading
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from database import (
    init_db, save_price_snapshots_bulk,
    record_disagreement, resolve_disagreement,
    record_depeg, resolve_depeg,
    get_recent_disagreements, get_active_disagreements,
    get_depeg_history, get_active_depegs,
    get_stats, get_price_history,
)
from oracles.aggregator import aggregate, get_last_result, SOURCE_COLORS
from oracles.config import CHAINS, STABLECOIN_SYMBOLS
from oracles import coingecko, binance
import bot as tgbot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

_bot_app = None
_bot_loop = None
_bot_ready = threading.Event()


# ── Background tasks ──────────────────────────────────────────────────────────

def run_price_cycle():
    """Aggregate prices, persist to DB, detect events, broadcast alerts."""
    global _bot_app, _bot_loop
    logger.info("Starting price cycle...")
    try:
        result = aggregate()

        # Persist snapshots
        rows = []
        for sym, source_prices in result.get("prices", {}).items():
            for src, price in source_prices.items():
                if price is not None:
                    rows.append((sym, src, None, price))
        if rows:
            save_price_snapshots_bulk(rows)

        # Record / resolve disagreements
        dis_symbols = set()
        for dis in result.get("disagreements", []):
            sym = dis["symbol"]
            dis_symbols.add(sym)
            record_disagreement(
                sym,
                dis["median"],
                dis["max_deviation_pct"],
                dis["severity"],
                dis.get("leading", ""),
                dis.get("lagging", ""),
                json.dumps(dis.get("prices", {})),
            )
        for sym in list(_active_dis_set):
            if sym not in dis_symbols:
                resolve_disagreement(sym)
                _active_dis_set.discard(sym)
        _active_dis_set.update(dis_symbols)

        # Record / resolve depeg events
        dep_symbols = set()
        for dep in result.get("depeg_alerts", []):
            sym = dep["symbol"]
            dep_symbols.add(sym)
            record_depeg(
                sym, dep["price"], dep["peg"],
                dep["deviation_pct"], dep["severity"],
                dep["direction"],
            )
        for sym in list(_active_dep_set):
            if sym not in dep_symbols:
                resolve_depeg(sym)
                _active_dep_set.discard(sym)
        _active_dep_set.update(dep_symbols)

        # Broadcast alerts via Telegram
        if _bot_app and _bot_loop and _bot_ready.is_set():
            new_dis = [d for d in result.get("disagreements", []) if d["symbol"] not in _notified_dis]
            new_dep = [d for d in result.get("depeg_alerts", []) if d["symbol"] not in _notified_dep]
            if new_dis or new_dep:
                asyncio.run_coroutine_threadsafe(
                    tgbot.broadcast_alerts(_bot_app, new_dis, new_dep),
                    _bot_loop,
                ).result(timeout=30)
            _notified_dis.update(d["symbol"] for d in result.get("disagreements", []))
            _notified_dep.update(d["symbol"] for d in result.get("depeg_alerts", []))
            # Clear resolved notifications
            for sym in list(_notified_dis):
                if sym not in dis_symbols:
                    _notified_dis.discard(sym)
            for sym in list(_notified_dep):
                if sym not in dep_symbols:
                    _notified_dep.discard(sym)

        logger.info(
            f"Price cycle done — "
            f"{len(rows)} snapshots, "
            f"{len(result.get('disagreements',[]))} disagreements, "
            f"{len(result.get('depeg_alerts',[]))} depeg alerts"
        )
    except Exception as e:
        logger.error(f"Price cycle error: {e}", exc_info=True)


_active_dis_set: set = set()
_active_dep_set: set = set()
_notified_dis: set = set()
_notified_dep: set = set()


def run_bot_thread():
    global _bot_app, _bot_loop

    async def _run():
        global _bot_app, _bot_loop
        _bot_app = tgbot.build_application()
        if not _bot_app:
            return
        _bot_loop = asyncio.get_event_loop()
        try:
            await _bot_app.initialize()
            await _bot_app.start()
            await _bot_app.updater.start_polling(allowed_updates=["message"])
            _bot_ready.set()
            logger.info("Telegram bot started")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            _bot_ready.set()
        await asyncio.Event().wait()

    asyncio.run(_run())


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/overview")
def api_overview():
    """Oracles summary — source names, chains, feed counts."""
    from oracles.chainlink import get_all_supported_chains as cl_chains, get_chain_feeds as cl_feeds
    from oracles.api3 import get_all_supported_chains as a3_chains, get_chain_feeds as a3_feeds
    from oracles.pyth import get_all_feeds as pyth_feeds

    sources = {
        "coingecko": {
            "name": "CoinGecko",
            "color": SOURCE_COLORS["coingecko"],
            "chains": ["off-chain"],
            "feed_count": len(coingecko.COINGECKO_IDS),
        },
        "binance": {
            "name": "Binance",
            "color": SOURCE_COLORS["binance"],
            "chains": ["off-chain"],
            "feed_count": len(binance.BINANCE_PAIRS),
        },
        "chainlink": {
            "name": "Chainlink",
            "color": SOURCE_COLORS["chainlink"],
            "chains": cl_chains(),
            "feed_count": sum(len(cl_feeds(c)) for c in cl_chains()),
        },
        "api3": {
            "name": "API3 dAPI",
            "color": SOURCE_COLORS["api3"],
            "chains": a3_chains(),
            "feed_count": len(a3_feeds("ethereum")),
        },
        "pyth": {
            "name": "Pyth Network",
            "color": SOURCE_COLORS["pyth"],
            "chains": ["multi-chain"],
            "feed_count": len(pyth_feeds()),
        },
    }
    return jsonify({"sources": sources, "chains": CHAINS})


@app.route("/api/prices")
def api_prices():
    result = get_last_result() or aggregate()
    return jsonify({
        "prices": result.get("prices", {}),
        "consensus": result.get("consensus", {}),
        "disagreements": result.get("disagreements", []),
        "depeg_alerts": result.get("depeg_alerts", []),
        "timestamp": result.get("timestamp"),
    })


@app.route("/api/chain/<chain_key>")
def api_chain(chain_key):
    chain = CHAINS.get(chain_key)
    if not chain:
        return jsonify({"error": "Unknown chain"}), 404

    result = get_last_result() or aggregate()
    prices = result.get("prices", {})
    consensus = result.get("consensus", {})

    coins = []
    for sym, sp in prices.items():
        if sp:
            coins.append({
                "symbol": sym,
                "consensus": consensus.get(sym),
                "sources": sp,
                "source_count": len(sp),
            })
    coins.sort(key=lambda x: x["symbol"])
    return jsonify({"chain": chain, "coins": coins})


@app.route("/api/coin/<symbol>")
def api_coin(symbol):
    sym = symbol.upper()
    result = get_last_result() or aggregate()
    prices = result.get("prices", {}).get(sym)
    if not prices:
        return jsonify({"error": "No data"}), 404
    median = result.get("consensus", {}).get(sym)
    dis = [d for d in result.get("disagreements", []) if d["symbol"] == sym]
    history = get_price_history(sym, limit=100)
    return jsonify({
        "symbol": sym,
        "prices": prices,
        "median": median,
        "disagreement": dis[0] if dis else None,
        "history": history,
        "is_stablecoin": sym in STABLECOIN_SYMBOLS,
    })


@app.route("/api/disagreements")
def api_disagreements():
    return jsonify({
        "active": get_active_disagreements(),
        "recent": get_recent_disagreements(30),
    })


@app.route("/api/depeg")
def api_depeg():
    return jsonify({
        "active": get_active_depegs(),
        "history": get_depeg_history(50),
    })


@app.route("/api/search")
def api_search():
    from flask import request
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    cg = coingecko.search(q)
    bn = binance.search(q)
    return jsonify({"coingecko": cg, "binance": bn})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()

    run_price_cycle()

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_price_cycle, "interval", minutes=5, id="price_cycle")
    scheduler.start()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
