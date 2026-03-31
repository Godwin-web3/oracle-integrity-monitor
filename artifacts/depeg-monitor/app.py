import os
import asyncio
import logging
import threading
from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from database import (
    init_db, get_depeg_history, get_price_chart_data, get_all_subscribers
)
from monitor import check_prices, get_current_prices, get_fetch_error, STABLECOINS
import bot as tgbot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

_bot_app = None
_bot_loop = None


def run_bot_in_thread():
    global _bot_app, _bot_loop

    async def start_bot():
        global _bot_app, _bot_loop
        _bot_app = tgbot.build_application()
        if not _bot_app:
            return
        _bot_loop = asyncio.get_event_loop()
        await _bot_app.initialize()
        await _bot_app.start()
        await _bot_app.updater.start_polling(allowed_updates=["message"])
        logger.info("Telegram bot started polling")
        await asyncio.Event().wait()

    asyncio.run(start_bot())


def run_price_check():
    global _bot_app, _bot_loop
    logger.info("Running scheduled price check...")
    try:
        results, alerts = check_prices()
        logger.info(f"Checked {len(results)} coins, {len(alerts)} alerts triggered")
        if alerts and _bot_app and _bot_loop:
            future = asyncio.run_coroutine_threadsafe(
                tgbot.send_depeg_alerts(_bot_app, alerts),
                _bot_loop
            )
            future.result(timeout=30)
    except Exception as e:
        logger.error(f"Price check error: {e}")


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/prices")
def api_prices():
    prices = get_current_prices()
    error = get_fetch_error()
    return jsonify({"prices": prices, "error": error})


@app.route("/api/depeg-history")
def api_depeg_history():
    history = get_depeg_history(limit=50)
    return jsonify({"events": history})


@app.route("/api/chart/<coin_id>")
def api_chart(coin_id):
    data = get_price_chart_data(coin_id, limit=288)
    return jsonify({"data": data})


@app.route("/api/stats")
def api_stats():
    prices = get_current_prices()
    history = get_depeg_history(limit=100)
    subscribers = get_all_subscribers()
    depegged_now = [p for p in prices if p.get("is_depegged")]
    return jsonify({
        "total_coins": len(prices),
        "depegged_now": len(depegged_now),
        "total_events_tracked": len(history),
        "total_subscribers": len(subscribers),
    })


@app.route("/api/coins")
def api_coins():
    return jsonify({"coins": [{"id": c["id"], "symbol": c["symbol"]} for c in STABLECOINS]})


if __name__ == "__main__":
    init_db()

    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()

    run_price_check()

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_price_check, "interval", minutes=5, id="price_check")
    scheduler.start()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask dashboard on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
