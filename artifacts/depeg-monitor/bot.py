"""Telegram bot with full multi-chain oracle commands."""
import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from database import (
    add_subscriber, remove_subscriber, is_subscriber, get_all_subscribers,
    get_subscriber, update_subscriber_thresholds,
    get_active_disagreements, get_recent_disagreements,
    get_active_depegs, get_depeg_history,
)
from oracles.aggregator import aggregate, compare_symbol, get_last_result
from oracles.config import CHAINS, STABLECOIN_SYMBOLS

logger = logging.getLogger(__name__)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(price: float | None) -> str:
    if price is None:
        return "—"
    if price < 0.001:
        return f"${price:.8f}"
    if price < 1:
        return f"${price:.6f}"
    if price < 100:
        return f"${price:.4f}"
    return f"${price:,.2f}"


def _pct(val: float) -> str:
    return f"{val*100:.3f}%"


def _severity_bar(severity: int) -> str:
    filled = "█" * severity
    empty = "░" * (10 - severity)
    return f"{filled}{empty}"


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔭 *Oracle Integrity Dashboard Bot*\n\n"
        "Monitor stablecoin depegs and oracle disagreements across 5 sources:\n"
        "CoinGecko · Binance · Chainlink · API3 · Pyth\n\n"
        "Commands:\n"
        "/subscribe — Get depeg & oracle alerts\n"
        "/unsubscribe — Stop alerts\n"
        "/status — All stablecoin prices across sources\n"
        "/compare <symbol> — All oracle prices for a coin\n"
        "/chain <chain> — Oracle feeds on a chain\n"
        "/alert — Recent oracle disagreements\n"
        "/setalert <pct> — Set disagreement threshold\n"
        "/search <query> — Search any coin\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)


async def subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    uname = update.effective_user.username or str(cid)
    if is_subscriber(cid):
        await update.message.reply_text("✅ Already subscribed! You'll get depeg and disagreement alerts.")
        return
    add_subscriber(cid, uname)
    await update.message.reply_text(
        "✅ *Subscribed!*\n\nYou'll receive:\n"
        "• 🔴 Depeg alerts when stablecoins leave their peg\n"
        "• ⚠️ Oracle disagreement alerts when sources diverge\n\n"
        "Use /setalert to customize thresholds.",
        parse_mode="Markdown",
    )


async def unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if remove_subscriber(cid):
        await update.message.reply_text("❌ Unsubscribed. Use /subscribe to re-enable alerts.")
    else:
        await update.message.reply_text("You're not subscribed. Use /subscribe to start.")


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching prices from all oracles...")
    agg = aggregate()
    prices = agg.get("prices", {})
    stables = sorted(STABLECOIN_SYMBOLS & prices.keys())

    if not stables:
        await update.message.reply_text("No stablecoin data available yet.")
        return

    lines = ["💲 *Stablecoin Prices — All Oracles*\n"]
    for sym in stables:
        sp = prices[sym]
        vals = list(sp.values())
        median = agg["consensus"].get(sym, 0)
        dev = abs(median - 1.0) if sym in STABLECOIN_SYMBOLS else 0
        badge = "🔴" if dev > 0.01 else ("🟡" if dev > 0.005 else "🟢")
        lines.append(f"{badge} *{sym}*: {_fmt(median)} (±{dev*100:.3f}%)")
        for src, p in sorted(sp.items()):
            lines.append(f"  `{src:12}` {_fmt(p)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def compare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Usage: /compare <symbol>\nExample: /compare ETH", parse_mode="Markdown"
        )
        return
    sym = ctx.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching {sym} prices from all oracles...")
    result = compare_symbol(sym)
    if not result:
        await update.message.reply_text(f"No data found for `{sym}`.", parse_mode="Markdown")
        return

    prices = result["prices"]
    median = result["median"]
    lines = [f"📊 *{sym} — Oracle Comparison*\n", f"Consensus: {_fmt(median)}\n"]
    for src, price in sorted(prices.items()):
        dev = abs(price - median) / median * 100 if median else 0
        flag = " ⚠️" if dev > 0.5 else ""
        lines.append(f"`{src:12}` {_fmt(price)} ({dev:+.3f}%){flag}")

    if result["disagreement"]:
        lines.append("\n⚠️ *Oracles disagree on this coin!*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def chain_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        chain_list = "\n".join(f"• `{k}` — {v['name']}" for k, v in CHAINS.items())
        await update.message.reply_text(
            f"Usage: /chain <chain_name>\n\nAvailable chains:\n{chain_list}",
            parse_mode="Markdown",
        )
        return

    chain_key = ctx.args[0].lower()
    chain_info = CHAINS.get(chain_key)
    if not chain_info:
        await update.message.reply_text(f"Unknown chain `{chain_key}`. Use /chain to list all.", parse_mode="Markdown")
        return

    await update.message.reply_text(f"⏳ Fetching oracle feeds for {chain_info['name']}...")
    agg = aggregate()
    prices = agg.get("prices", {})
    by_source = agg.get("by_source", {})

    # Collect symbols available from CL or API3 on this chain
    # We approximate by showing all symbols with prices
    lines = [f"⛓ *{chain_info['name']} — Oracle Feeds*\n"]
    count = 0
    for sym in sorted(prices.keys())[:30]:
        sp = prices[sym]
        if sp:
            median = agg["consensus"].get(sym, 0)
            lines.append(f"• *{sym}*: {_fmt(median)} ({len(sp)} sources)")
            count += 1

    if not count:
        lines.append("No feed data available for this chain yet.")
    else:
        lines.append(f"\n_{count} coins shown. Full list in the dashboard._")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    dis = get_recent_disagreements(10)
    deps = get_depeg_history(5)

    lines = ["⚠️ *Recent Oracle Disagreements*\n"]
    if not dis:
        lines.append("No disagreements recorded yet.\n")
    else:
        for d in dis[:8]:
            sev = d.get("severity", 0)
            bar = _severity_bar(sev)
            lines.append(
                f"*{d['symbol']}* — {d['max_deviation_pct']:.3f}% gap\n"
                f"Severity: [{bar}] {sev}/10\n"
                f"Lead: {d.get('leading_source','?')} | Lag: {d.get('lagging_source','?')}\n"
            )

    lines.append("\n🔴 *Depeg Events*\n")
    if not deps:
        lines.append("No depeg events recorded yet.")
    else:
        for d in deps[:5]:
            lines.append(
                f"*{d['symbol']}* — {_fmt(d['price'])} "
                f"({d['deviation_pct']:.3f}% {d['direction']} peg)\n"
                f"Severity: {d['severity']}/10\n"
            )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def setalert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not ctx.args:
        sub = get_subscriber(cid)
        if sub:
            await update.message.reply_text(
                f"Current thresholds:\n"
                f"• Disagreement: *{sub['disagreement_threshold']*100:.2f}%*\n"
                f"• Depeg: *{sub['depeg_threshold']*100:.2f}%*\n\n"
                f"Usage: `/setalert <disagreement_pct> [depeg_pct]`\n"
                f"Example: `/setalert 0.5 1.0`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Use /subscribe first, then /setalert.")
        return

    try:
        dis_val = float(ctx.args[0]) / 100
        dep_val = float(ctx.args[1]) / 100 if len(ctx.args) > 1 else None
        if not is_subscriber(cid):
            add_subscriber(cid, update.effective_user.username or str(cid))
        update_subscriber_thresholds(cid, dis_val, dep_val)
        msg = f"✅ Disagreement threshold set to *{dis_val*100:.2f}%*"
        if dep_val:
            msg += f"\nDepeg threshold set to *{dep_val*100:.2f}%*"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Usage: `/setalert <disagreement_pct> [depeg_pct]`\nExample: `/setalert 0.5 1.0`",
            parse_mode="Markdown",
        )


async def search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /search <query>\nExample: /search bitcoin")
        return
    query = " ".join(ctx.args)
    from oracles import coingecko, binance
    await update.message.reply_text(f"🔍 Searching for `{query}`...", parse_mode="Markdown")

    cg_results = coingecko.search(query)
    bn_results = binance.search(query)

    lines = [f"🔍 *Search results for '{query}'*\n"]

    if cg_results:
        lines.append("*CoinGecko:*")
        for r in cg_results[:5]:
            price = coingecko.get_price_for_id(r["id"])
            price_str = _fmt(price) if price else "—"
            lines.append(f"• {r['name']} (`{r['symbol']}`) — {price_str}")

    if bn_results:
        lines.append("\n*Binance:*")
        for r in bn_results[:5]:
            lines.append(f"• `{r['symbol']}` — {_fmt(r['price'])}")

    if not cg_results and not bn_results:
        lines.append("No results found.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Alert broadcast ────────────────────────────────────────────────────────────

async def broadcast_alerts(app: Application, disagreements: list, depeg_alerts: list):
    subscribers = get_all_subscribers()
    if not subscribers:
        return

    for dis in disagreements:
        msg = (
            f"⚠️ *Oracle Disagreement: {dis['symbol']}*\n\n"
            f"Max gap: *{dis['max_deviation_pct']:.3f}%*\n"
            f"Severity: {dis['severity']}/10\n"
            f"Leading: {dis.get('leading', '?')}\n"
            f"Lagging: {dis.get('lagging', '?')}\n\n"
            "Prices:\n"
        )
        for src, p in dis.get("prices", {}).items():
            msg += f"  `{src}`: {_fmt(p)}\n"

        for sub in subscribers:
            if dis["max_deviation"] >= sub.get("disagreement_threshold", 0.005):
                try:
                    await app.bot.send_message(
                        chat_id=sub["chat_id"], text=msg, parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Broadcast disagreement to {sub['chat_id']}: {e}")

    for dep in depeg_alerts:
        msg = (
            f"🚨 *Depeg Alert: {dep['symbol']}*\n\n"
            f"Price: {_fmt(dep['price'])}\n"
            f"Peg: {_fmt(dep['peg'])}\n"
            f"Deviation: *{dep['deviation_pct']:.3f}%* {dep['direction']} peg\n"
            f"Severity: {dep['severity']}/10\n"
        )
        for sub in subscribers:
            if dep["deviation"] >= sub.get("depeg_threshold", 0.01):
                try:
                    await app.bot.send_message(
                        chat_id=sub["chat_id"], text=msg, parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Broadcast depeg to {sub['chat_id']}: {e}")


def build_application() -> Application | None:
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return None
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("compare", compare))
    app.add_handler(CommandHandler("chain", chain_cmd))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("setalert", setalert))
    app.add_handler(CommandHandler("search", search))
    return app
