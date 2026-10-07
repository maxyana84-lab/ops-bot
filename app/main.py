"""Entry point: Telegram bot + webhook HTTP server in a single asyncio process."""

from __future__ import annotations

import logging
import time
from functools import wraps
from html import escape

import httpx
from aiohttp import web
from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .config import Settings, load_settings
from .formatting import format_status, format_transition
from .health import StateTracker, check_all
from .metrics import (
    COMMANDS_TOTAL,
    MESSAGES_SENT_TOTAL,
    SEND_ERRORS_TOTAL,
    TARGET_LATENCY,
    TARGET_UP,
)
from .webhooks import build_web_app

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# httpx logs every request URL, which would include the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("opsbot")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

COMMANDS = [
    BotCommand("status", "Check all targets now"),
    BotCommand("targets", "List monitored targets"),
    BotCommand("mute", "Mute alerts: /mute 30 (minutes)"),
    BotCommand("unmute", "Unmute alerts"),
    BotCommand("uptime", "Bot uptime"),
    BotCommand("help", "Show help"),
]

HELP_TEXT = (
    "<b>Ops Bot</b> — alerts and service status.\n\n"
    "/status — check all targets now\n"
    "/targets — list monitored targets\n"
    "/mute 30 — mute alerts for 30 minutes\n"
    "/unmute — unmute alerts\n"
    "/uptime — bot uptime\n\n"
    "Webhooks: <code>POST /webhook/alertmanager</code>, <code>POST /webhook/notify</code>"
)


def settings_of(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def restricted(func):
    """Allow a command only from chats listed in ALLOWED_CHAT_IDS."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None or chat.id not in settings_of(context).allowed_chat_ids:
            log.warning("Denied %s from chat %s", func.__name__, chat.id if chat else None)
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Access denied.")
            return None
        COMMANDS_TOTAL.labels(func.__name__.removesuffix("_cmd")).inc()
        return await func(update, context)

    return wrapper


async def broadcast(app: Application, text: str, *, force: bool = False) -> None:
    """Send a message to every alert chat, unless alerts are muted."""
    muted_until = app.bot_data.get("muted_until", 0.0)
    if not force and time.time() < muted_until:
        log.info("Alert suppressed (muted): %s", text.splitlines()[0])
        return
    for chat_id in app.bot_data["settings"].alert_chat_ids:
        try:
            await app.bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW
            )
            MESSAGES_SENT_TOTAL.inc()
        except TelegramError:
            SEND_ERRORS_TOTAL.inc()
            log.exception("Failed to send message to chat %s", chat_id)


async def run_checks(app: Application):
    settings: Settings = app.bot_data["settings"]
    results = await check_all(app.bot_data["http"], settings.targets)
    for r in results:
        TARGET_UP.labels(r.target.name).set(1 if r.ok else 0)
        if r.ok and r.latency_ms is not None:
            TARGET_LATENCY.labels(r.target.name).set(r.latency_ms / 1000)
    return results


# --- Commands -----------------------------------------------------------------


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open to everyone so a new user can discover their chat id during setup."""
    chat_id = update.effective_chat.id
    allowed = chat_id in settings_of(context).allowed_chat_ids
    text = f"Your chat id: <code>{chat_id}</code>\n"
    text += HELP_TEXT if allowed else "Add it to ALLOWED_CHAT_IDS / ALERT_CHAT_IDS to get access."
    await update.message.reply_html(text)


@restricted
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


@restricted
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    results = await run_checks(context.application)
    await update.message.reply_html(format_status(results), link_preview_options=NO_PREVIEW)


@restricted
async def targets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    targets = settings_of(context).targets
    if not targets:
        await update.message.reply_text("No targets configured.")
        return
    lines = [f"• <b>{escape(t.name)}</b> — <code>{escape(t.url)}</code>" for t in targets]
    await update.message.reply_html("\n".join(lines), link_preview_options=NO_PREVIEW)


@restricted
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        minutes = int(context.args[0]) if context.args else 60
    except ValueError:
        await update.message.reply_text("Usage: /mute <minutes>")
        return
    minutes = max(1, min(minutes, 24 * 60))
    context.bot_data["muted_until"] = time.time() + minutes * 60
    await update.message.reply_text(f"🔕 Alerts muted for {minutes} min.")


@restricted
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["muted_until"] = 0.0
    await update.message.reply_text("🔔 Alerts unmuted.")


@restricted
async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seconds = int(time.time() - context.bot_data["started_at"])
    hours, rest = divmod(seconds, 3600)
    await update.message.reply_text(f"⏱ Up {hours}h {rest // 60}m")


# --- Background job & lifecycle -----------------------------------------------


async def periodic_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    results = await run_checks(app)
    for result, transition in app.bot_data["tracker"].update(results):
        await broadcast(app, format_transition(result, transition))


async def on_startup(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    app.bot_data["started_at"] = time.time()
    app.bot_data["http"] = httpx.AsyncClient(headers={"User-Agent": "ops-bot/1.0"})

    web_app = build_web_app(settings.webhook_secret, lambda text: broadcast(app, text))
    runner = web.AppRunner(web_app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, settings.http_host, settings.http_port).start()
    app.bot_data["runner"] = runner
    log.info("HTTP server listening on %s:%s", settings.http_host, settings.http_port)

    await app.bot.set_my_commands(COMMANDS)
    if not settings.alert_chat_ids:
        log.warning("ALERT_CHAT_IDS is empty: alerts won't be delivered. Send /start to the bot.")


async def on_shutdown(app: Application) -> None:
    if runner := app.bot_data.get("runner"):
        await runner.cleanup()
    if client := app.bot_data.get("http"):
        await client.aclose()


def build_application(settings: Settings) -> Application:
    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["tracker"] = StateTracker(settings.failure_threshold)

    for name, handler in [
        ("start", start_cmd),
        ("help", help_cmd),
        ("status", status_cmd),
        ("targets", targets_cmd),
        ("mute", mute_cmd),
        ("unmute", unmute_cmd),
        ("uptime", uptime_cmd),
    ]:
        app.add_handler(CommandHandler(name, handler))

    if settings.targets:
        app.job_queue.run_repeating(periodic_check, interval=settings.check_interval, first=10)
    return app


def main() -> None:
    settings = load_settings()
    log.info("Starting ops-bot with %d target(s)", len(settings.targets))
    build_application(settings).run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
