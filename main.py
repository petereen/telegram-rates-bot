"""
main.py – application entry point.

Imports all provider modules to trigger @register_provider decorators,
then builds and starts the Telegram bot.
"""

import logging

from telegram.ext import ApplicationBuilder

from config import TELEGRAM_BOT_TOKEN
from bot.handlers import register_handlers

# ── Import providers so their @register_provider decorators run ────────
import providers.cbr       # noqa: F401
import providers.xe        # noqa: F401
import providers.binance   # noqa: F401
import providers.profinance  # noqa: F401
import providers.boc       # noqa: F401
import providers.grx       # noqa: F401


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Starting Exchange Rates Bot …")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    register_handlers(app)
    log.info("Bot is polling.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
