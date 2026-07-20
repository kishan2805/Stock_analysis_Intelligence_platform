"""One-off Telegram notifications initiated from the authenticated Admin page."""
from __future__ import annotations

from .config import load_telegram_config


async def send_rejection_notification(chat_id: int, kind: str, target: str) -> None:
    """Tell a requester that their queued job was declined before compute started."""
    from telegram import Bot

    label = "stock" if kind == "stock" else "YouTube video"
    message = (
        f"Sorry, your SAIP {label} analysis request for {target} was not started because it was declined by an administrator. "
        "Please contact the administrator if you need help."
    )
    config = load_telegram_config()
    async with Bot(config.token) as bot:
        await bot.send_message(chat_id=chat_id, text=message)


async def send_cancellation_notification(chat_id: int, kind: str, target: str) -> None:
    """Tell a requester that an already-started job was stopped by an admin."""
    from telegram import Bot

    label = "stock" if kind == "stock" else "YouTube video"
    message = (
        f"Sorry, your SAIP {label} analysis request for {target} was stopped before it could be completed by an administrator. "
        "Please contact the administrator if you need help."
    )
    config = load_telegram_config()
    async with Bot(config.token) as bot:
        await bot.send_message(chat_id=chat_id, text=message)
