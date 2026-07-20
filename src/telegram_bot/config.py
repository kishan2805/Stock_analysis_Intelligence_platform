"""Configuration for the standalone SAIP Telegram bot process."""
from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    admin_user_id: int


def load_telegram_config() -> TelegramConfig:
    """Load required bot credentials without ever logging their values."""
    load_dotenv()
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    admin_value = (os.getenv("TELEGRAM_ADMIN_USER_ID") or "").strip()
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_ADMIN_USER_ID", admin_value),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required Telegram environment variable(s): " + ", ".join(missing))
    try:
        admin_user_id = int(admin_value)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_ADMIN_USER_ID must be a numeric Telegram user ID.") from exc
    return TelegramConfig(token=token, admin_user_id=admin_user_id)
