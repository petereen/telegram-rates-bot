"""
main.py – application entry point.

Imports all provider modules to trigger @register_provider decorators,
then builds and starts the Telegram bot.
"""

import logging
import threading

from telegram.ext import ApplicationBuilder

from config import TELEGRAM_BOT_TOKEN
from bot.handlers import register_handlers
from providers.mongolbank import run_daily_refresh
from providers.registry import register_all_providers


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Starting Exchange Rates Bot …")
    register_all_providers()
    threading.Thread(
        target=run_daily_refresh,
        name="mongolbank-daily-refresh",
        daemon=True,
    ).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    register_handlers(app)
    log.info("Bot is polling.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
