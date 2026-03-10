"""
bot/main.py — Telegram bot entry point.
Starts the bot and registers all handlers.
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import start, subscription
from database import init_db
import config

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🚀 Starting bot...")

    # Initialize database
    await init_db()
    logger.info("✅ Database initialized")

    # Create bot and dispatcher
    bot        = Bot(token=config.BOT_TOKEN)
    dp         = Dispatcher(storage=MemoryStorage())

    # Inject bot into callback server
    from payments.callbacks import set_bot
    set_bot(bot)

    # Register routers
    dp.include_router(start.router)
    dp.include_router(subscription.router)

    logger.info("✅ Handlers registered")
    logger.info("🤖 Bot is polling for updates...")

    # Start polling
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())