"""Long-polling Telegram interface for SAIP."""
from __future__ import annotations

import logging
import sqlite3
from urllib.parse import parse_qs, urlparse

try:
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.constants import ChatType
    from telegram.error import BadRequest
    from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only when starting the optional service
    raise RuntimeError("Install the project dependencies before starting the Telegram bot: pip install -r requirements.txt") from exc

from src.youtube_signals.monitoring import ChannelStore

from .config import TelegramConfig, load_telegram_config
from .service import TelegramAnalysisService, TelegramFCFSQueue, TelegramVideoAnalysisService
from .stocks import StockRequest, resolve_stock_options
from .store import TelegramStore, TelegramUser

logger = logging.getLogger(__name__)


def _is_youtube_channel_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    is_youtube = host in {"youtube.com", "www.youtube.com", "m.youtube.com"}
    channel_path = parsed.path.startswith(("/@", "/channel/", "/c/", "/user/"))
    return parsed.scheme in {"http", "https"} and is_youtube and channel_path


def _is_youtube_video_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    if parsed.scheme not in {"http", "https"}:
        return False
    if host == "youtu.be":
        return bool(parsed.path.strip("/"))
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return False
    return (
        (parsed.path == "/watch" and bool(parse_qs(parsed.query).get("v")))
        or parsed.path.startswith("/shorts/")
        or parsed.path.startswith("/live/")
    )


def _private_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


async def _require_private_chat(update: Update) -> bool:
    if _private_chat(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("For privacy, please open a private chat with this bot and use the command there.")
    return False


def _profile(update: Update, store: TelegramStore) -> TelegramUser:
    user, chat = update.effective_user, update.effective_chat
    if not user or not chat:
        raise ValueError("Telegram user and chat are required.")
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip() or user.username or str(user.id)
    return store.ensure_user(user.id, chat.id, name, user.username)


def _channel_view(user: TelegramUser, store: ChannelStore) -> tuple[str, InlineKeyboardMarkup]:
    channels = store.list_channels(user.subject_id)
    lines = ["Your YouTube channel subscriptions:"]
    buttons: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton("➕ Add a YouTube channel", callback_data="channels:add"),
        InlineKeyboardButton("▶ Analyse a YouTube video", callback_data="videos:add"),
    ]]
    if not channels:
        lines.append("None yet. Add a public YouTube channel to include it in your private scan list.")
    for channel in channels:
        state = "enabled" if channel.enabled else "disabled"
        lines.append(f"• {channel.label} — {state}")
        buttons.append([
            InlineKeyboardButton("Disable" if channel.enabled else "Enable", callback_data=f"channels:toggle:{channel.id}"),
            InlineKeyboardButton("Remove", callback_data=f"channels:delete:{channel.id}"),
        ])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def _settings_view(user: TelegramUser) -> tuple[str, InlineKeyboardMarkup]:
    notifications = "On" if user.notifications_enabled else "Off"
    text = (
        "Preferences\n"
        f"Scheduled recommendation notifications: {notifications}\n"
        f"Default analysis horizon: {user.duration_months} months\n"
        f"Default analysis depth: {user.analysis_depth}\n\n"
        "These defaults are used for new /analyze requests."
    )
    buttons = [
        [InlineKeyboardButton(f"Notifications: {notifications}", callback_data="settings:notifications")],
        [
            InlineKeyboardButton("Quick", callback_data="settings:depth:quick"),
            InlineKeyboardButton("Balanced", callback_data="settings:depth:balanced"),
            InlineKeyboardButton("Premium", callback_data="settings:depth:premium"),
        ],
        [
            InlineKeyboardButton("6 months", callback_data="settings:duration:6"),
            InlineKeyboardButton("18 months", callback_data="settings:duration:18"),
            InlineKeyboardButton("36 months", callback_data="settings:duration:36"),
        ],
    ]
    return text, InlineKeyboardMarkup(buttons)


async def _edit_message_if_changed(query, text: str, keyboard: InlineKeyboardMarkup) -> None:
    """Telegram rejects a no-op edit; repeated button taps are harmless."""
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    store: TelegramStore = context.application.bot_data["telegram_store"]
    config: TelegramConfig = context.application.bot_data["telegram_config"]
    user = _profile(update, store)
    admin_note = "\nAdmin identity verified." if user.telegram_user_id == config.admin_user_id else ""
    await update.effective_message.reply_text(
        "Welcome to SAIP. I can manage public YouTube channel subscriptions and create private stock-analysis reports.\n\n"
        "Use /channels to manage sources, /analyze RELIANCE.NS to request analysis, and /help for all commands.\n\n"
        "Informational research only — not investment advice." + admin_note
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    await update.effective_message.reply_text(
        "SAIP commands\n\n"
        "/start — start the bot\n"
        "/help — show this help\n"
        "/channels — manage public YouTube channel subscriptions\n"
        "/analyze RELIANCE.NS — request a private stock analysis\n"
        "/analyze <YouTube video URL> — analyse one public video\n"
        "/report [TICKER] — get your newest completed report\n"
        "/settings — notification and analysis preferences\n\n"
        "Use canonical NSE tickers such as RELIANCE.NS or US tickers such as AAPL."
    )


async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    user = _profile(update, context.application.bot_data["telegram_store"])
    source_url = " ".join(context.args).strip()
    if source_url:
        await _save_channel(update, context, user, source_url)
        return
    text, keyboard = _channel_view(user, context.application.bot_data["channel_store"])
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def _save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, user: TelegramUser, value: str) -> bool:
    """Validate and persist one public YouTube source for the requesting user."""
    if not _is_youtube_channel_url(value):
        await update.effective_message.reply_text(
            "Please send a public YouTube channel URL, for example https://www.youtube.com/@Channel/videos. "
            "Video links and Telegram channel links are not supported here."
        )
        return False
    channel_store: ChannelStore = context.application.bot_data["channel_store"]
    try:
        channel_store.add_channel(user.subject_id, value)
    except sqlite3.IntegrityError:
        await update.effective_message.reply_text("That YouTube channel is already in your scan list.")
        return False
    except Exception:
        logger.exception("Unable to add channel")
        await update.effective_message.reply_text("I could not add that channel. Please verify the URL and try again.")
        return False
    context.user_data.pop("awaiting", None)
    text, keyboard = _channel_view(user, channel_store)
    await update.effective_message.reply_text("Channel added.\n\n" + text, reply_markup=keyboard)
    return True


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    user = _profile(update, context.application.bot_data["telegram_store"])
    value = " ".join(context.args).strip()
    if not value:
        context.user_data["awaiting"] = "ticker"
        await update.effective_message.reply_text("Send a ticker such as RELIANCE.NS or AAPL. I will queue a private report.")
        return
    if _is_youtube_video_url(value):
        await _queue_video_analysis(update, context, user, value)
        return
    await _queue_analysis(update, context, user, value)


async def _queue_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, user: TelegramUser, value: str) -> None:
    options = resolve_stock_options(value)
    if not options:
        await update.effective_message.reply_text(
            "I could not safely identify that stock. Use an NSE ticker such as RELIANCE.NS or a US ticker such as AAPL."
        )
        return
    if len(options) > 1:
        context.user_data["stock_market_options"] = options
        buttons = [[
            InlineKeyboardButton(
                f"India (NSE) — {option.ticker}" if option.exchange == "IN" else f"United States — {option.ticker}",
                callback_data=f"stocks:choose:{index}",
            )
        ] for index, option in enumerate(options)]
        await update.effective_message.reply_text(
            f"{value.strip()} can refer to more than one market. Choose the correct exchange, or send the exact ticker.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    await _queue_stock_request(update, context, user, options[0])


async def _queue_stock_request(update: Update, context: ContextTypes.DEFAULT_TYPE, user: TelegramUser, request: StockRequest) -> None:
    context.user_data.pop("awaiting", None)
    context.user_data.pop("stock_market_options", None)
    service: TelegramAnalysisService = context.application.bot_data["analysis_service"]
    job = service.queue_analysis(user, request.ticker, request.exchange)
    context.application.bot_data["analysis_queue"].start()
    await update.effective_message.reply_text(
        f"Analysis queued for {job.ticker} ({job.exchange}) in first-come-first-served order. I will send the private summary and PDF when it is complete."
    )


async def _queue_video_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, user: TelegramUser, video_url: str) -> None:
    context.user_data.pop("awaiting", None)
    service: TelegramVideoAnalysisService = context.application.bot_data["video_analysis_service"]
    job = service.queue_video(user, video_url)
    context.application.bot_data["analysis_queue"].start()
    await update.effective_message.reply_text(
        f"YouTube video analysis queued ({job.id[:8]}). I will send the ranked stock summary and PDF when it is complete."
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    store: TelegramStore = context.application.bot_data["telegram_store"]
    user = _profile(update, store)
    ticker = " ".join(context.args).strip().upper() or None
    job = store.latest_completed_report(user.subject_id, ticker)
    if not job:
        suffix = f" for {ticker}" if ticker else ""
        await update.effective_message.reply_text(f"No completed private report is available{suffix}. Use /analyze to create one.")
        return
    delivered = await context.application.bot_data["analysis_service"].send_latest_report(job)
    if not delivered:
        await update.effective_message.reply_text("That report record is incomplete. Please run /analyze again.")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    user = _profile(update, context.application.bot_data["telegram_store"])
    text, keyboard = _settings_view(user)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not await _require_private_chat(update):
        return
    await query.answer()
    store: TelegramStore = context.application.bot_data["telegram_store"]
    channel_store: ChannelStore = context.application.bot_data["channel_store"]
    user = _profile(update, store)
    data = query.data or ""
    if data == "channels:add":
        context.user_data["awaiting"] = "channel"
        await query.message.reply_text("Send a public YouTube channel URL, for example https://www.youtube.com/@Channel/videos")
        return
    if data == "videos:add":
        context.user_data["awaiting"] = "video"
        await query.message.reply_text("Send a public YouTube video URL, for example https://www.youtube.com/watch?v=VIDEO_ID")
        return
    if data.startswith("stocks:choose:"):
        try:
            option_index = int(data.rsplit(":", 1)[1])
            options = context.user_data.get("stock_market_options") or ()
            request = options[option_index]
        except (IndexError, TypeError, ValueError):
            await query.message.reply_text("That stock choice has expired. Please use /analyze again and send the ticker.")
            return
        await _queue_stock_request(update, context, user, request)
        return
    if data.startswith("channels:"):
        try:
            action, channel_id = data.split(":")[1:]
            channel = next(item for item in channel_store.list_channels(user.subject_id) if item.id == int(channel_id))
            if action == "toggle":
                channel_store.set_enabled(user.subject_id, channel.id, not channel.enabled)
            elif action == "delete":
                channel_store.delete_channel(user.subject_id, channel.id)
            else:
                return
        except (ValueError, StopIteration):
            await query.message.reply_text("That channel is no longer available.")
            return
        text, keyboard = _channel_view(user, channel_store)
        await _edit_message_if_changed(query, text, keyboard)
        return
    if data == "settings:notifications":
        user = store.update_preferences(user.subject_id, notifications_enabled=not user.notifications_enabled)
    elif data.startswith("settings:depth:"):
        user = store.update_preferences(user.subject_id, analysis_depth=data.rsplit(":", 1)[1])
    elif data.startswith("settings:duration:"):
        try:
            user = store.update_preferences(user.subject_id, duration_months=int(data.rsplit(":", 1)[1]))
        except ValueError:
            return
    else:
        return
    text, keyboard = _settings_view(user)
    await _edit_message_if_changed(query, text, keyboard)


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_private_chat(update):
        return
    waiting = context.user_data.get("awaiting")
    if not waiting:
        value = (update.effective_message.text or "").strip()
        if _is_youtube_video_url(value):
            user = _profile(update, context.application.bot_data["telegram_store"])
            await _queue_video_analysis(update, context, user, value)
            return
        await update.effective_message.reply_text("Use /help to see the available commands.")
        return
    user = _profile(update, context.application.bot_data["telegram_store"])
    value = (update.effective_message.text or "").strip()
    if waiting == "ticker":
        await _queue_analysis(update, context, user, value)
        return
    if waiting == "channel":
        await _save_channel(update, context, user, value)
        return
    if waiting == "video":
        if not _is_youtube_video_url(value):
            await update.effective_message.reply_text("Please send a public YouTube video URL, such as https://www.youtube.com/watch?v=VIDEO_ID")
            return
        await _queue_video_analysis(update, context, user, value)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram update error", exc_info=context.error)


def build_application(config: TelegramConfig | None = None) -> Application:
    config = config or load_telegram_config()
    telegram_store, channel_store = TelegramStore(), ChannelStore()

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Help"),
            BotCommand("channels", "Manage subscriptions"),
            BotCommand("analyze", "Analyze a stock or YouTube video"),
            BotCommand("report", "Get latest report"),
            BotCommand("settings", "Preferences"),
        ])
        application.bot_data["telegram_store"].requeue_interrupted_jobs()
        application.bot_data["analysis_queue"].start()

    application = ApplicationBuilder().token(config.token).post_init(post_init).build()
    stock_service = TelegramAnalysisService(application.bot, telegram_store)
    video_service = TelegramVideoAnalysisService(application.bot, telegram_store)
    application.bot_data.update({
        "telegram_config": config,
        "telegram_store": telegram_store,
        "channel_store": channel_store,
        "analysis_service": stock_service,
        "video_analysis_service": video_service,
        "analysis_queue": TelegramFCFSQueue(telegram_store, stock_service, video_service),
    })
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("channels", channels))
    application.add_handler(CommandHandler("analyze", analyze))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
    application.add_error_handler(error_handler)
    return application
