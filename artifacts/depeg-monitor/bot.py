import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from database import (
    add_subscriber, remove_subscriber, is_subscriber,
    get_all_subscribers, update_alert_threshold,
    get_subscriber_threshold
)
from monitor import get_current_prices

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def format_price_list(prices):
    if not prices:
        return "No price data available yet. Prices update every 5 minutes."
    lines = []
    for p in sorted(prices, key=lambda x: x["symbol"]):
        status = "🔴 DEPEGGED" if p["is_depegged"] else "🟢 Stable"
        dev_pct = p["deviation"] * 100
        peg_display = f"${p['peg']:.6f}" if p["peg"] < 0.01 else f"${p['peg']:.4f}"
        price_display = f"${p['price']:.6f}" if p["price"] < 0.01 else f"${p['price']:.4f}"
        lines.append(
            f"*{p['symbol']}*: {price_display} | Peg: {peg_display} | Dev: {dev_pct:.3f}% {status}"
        )
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 *Welcome to StablecoinWatch Bot!*\n\n"
        "I monitor major stablecoins and alert you when they depeg.\n\n"
        "Tracked coins: USDT, USDC, DAI, FRAX, TUSD, PYUSD, cNGN, bNGN\n\n"
        "Commands:\n"
        "/subscribe — Get depeg alerts\n"
        "/unsubscribe — Stop alerts\n"
        "/status — See live prices\n"
        "/setalert <percent> — Set custom alert threshold (default 1%)\n"
        "/help — Show this help\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*StablecoinWatch Bot — Help*\n\n"
        "/start — Introduction\n"
        "/subscribe — Subscribe to depeg alerts\n"
        "/unsubscribe — Unsubscribe from alerts\n"
        "/status — View current prices and depeg status\n"
        "/setalert <percent> — Set your alert threshold\n"
        "  Example: `/setalert 0.5` alerts at 0.5% depeg\n"
        "/help — This help message\n\n"
        "A depeg is detected when a stablecoin price deviates from its $1.00 peg by your threshold (default 1%)."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name or str(chat_id)
    if is_subscriber(chat_id):
        await update.message.reply_text("✅ You're already subscribed! You'll receive depeg alerts automatically.")
        return
    add_subscriber(chat_id, username)
    await update.message.reply_text(
        "✅ *Subscribed!* You'll now receive alerts when any stablecoin depegs.\n\n"
        "Use /status to see current prices.",
        parse_mode="Markdown"
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if remove_subscriber(chat_id):
        await update.message.reply_text("❌ Unsubscribed. You won't receive depeg alerts anymore.\nUse /subscribe to re-enable alerts.")
    else:
        await update.message.reply_text("You weren't subscribed. Use /subscribe to start receiving alerts.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = get_current_prices()
    if not prices:
        await update.message.reply_text("⏳ Fetching prices... Please try again in a moment.")
        return

    depegged = [p for p in prices if p["is_depegged"]]
    header = "🚨 *DEPEG ALERT — Some stablecoins are off-peg!*\n\n" if depegged else "✅ *All monitored stablecoins are stable.*\n\n"

    price_text = format_price_list(prices)
    text = header + "*Current Prices:*\n" + price_text
    await update.message.reply_text(text, parse_mode="Markdown")


async def setalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        current = get_subscriber_threshold(chat_id) * 100
        await update.message.reply_text(
            f"Your current alert threshold is *{current:.2f}%*.\n\n"
            f"To change it, use: `/setalert <percent>`\nExample: `/setalert 0.5`",
            parse_mode="Markdown"
        )
        return
    try:
        val = float(context.args[0])
        if val <= 0 or val > 50:
            raise ValueError
        threshold = val / 100
        if not is_subscriber(chat_id):
            add_subscriber(chat_id, update.effective_user.username or str(chat_id), threshold)
        else:
            update_alert_threshold(chat_id, threshold)
        await update.message.reply_text(
            f"✅ Alert threshold set to *{val:.2f}%*.\nYou'll be alerted when deviation exceeds this.",
            parse_mode="Markdown"
        )
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Invalid value. Use a number between 0.1 and 50.\nExample: `/setalert 1`",
            parse_mode="Markdown"
        )


async def send_depeg_alerts(app: Application, alerts: list):
    if not alerts:
        return
    subscribers = get_all_subscribers()
    for alert in alerts:
        direction_emoji = "📉" if alert["direction"] == "below" else "📈"
        msg = (
            f"🚨 *DEPEG ALERT: {alert['symbol']}*\n\n"
            f"{direction_emoji} Price has moved *{alert['direction']}* peg!\n"
            f"Current Price: ${alert['price']:.6f}\n"
            f"Target Peg: ${alert['peg']:.6f}\n"
            f"Deviation: *{alert['deviation']*100:.3f}%*\n\n"
            f"Use /status to see all coins."
        )
        dev = alert["deviation"]
        for sub in subscribers:
            if dev >= sub.get("alert_threshold", 0.01):
                try:
                    await app.bot.send_message(
                        chat_id=sub["chat_id"],
                        text=msg,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send to {sub['chat_id']}: {e}")


def build_application():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return None

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setalert", setalert))
    return app
