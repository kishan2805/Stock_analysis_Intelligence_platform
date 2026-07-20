"""Run SAIP's Telegram bot using long polling."""
from __future__ import annotations

import logging

from .bot import build_application
from .worker import TelegramWorkerManager


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # HTTP request URLs contain the bot token. Keep httpx at warning level so
    # terminal and admin-page logs never expose it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    manager = TelegramWorkerManager()
    manager.register_current_process()
    try:
        build_application().run_polling(drop_pending_updates=False)
    finally:
        manager.unregister_current_process()


if __name__ == "__main__":
    main()
