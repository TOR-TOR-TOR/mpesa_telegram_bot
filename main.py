"""
main.py — Single entry point that runs both the bot and callback server together.
Starts:
  - Aiogram bot (polling)
  - FastAPI callback server (uvicorn on port 8000)
Both run concurrently in the same async event loop.
"""

import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import start, subscription
from payments.callbacks import app as fastapi_app, set_bot
from database import init_db
import config

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def run_bot(bot: Bot, dp: Dispatcher):
    """Run the Telegram bot with long polling."""
    logger.info("🤖 Starting Telegram bot...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


async def run_server():
    """Run the FastAPI callback server."""
    logger.info(f"🌐 Starting callback server on port {config.PORT}...")
    server_config = uvicorn.Config(
        app       = fastapi_app,
        host      = "0.0.0.0",
        port      = config.PORT,
        log_level = "warning"   # suppress uvicorn noise, we use our own logger
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    logger.info("🚀 Kilima Bot starting up...")

    # Initialize database tables
    await init_db()
    logger.info("✅ Database ready")

    # Create bot and dispatcher
    bot = Bot(token=config.BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    # Inject bot into callback server so it can send messages
    set_bot(bot)
    logger.info("✅ Bot injected into callback server")

    # Register all handlers
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    logger.info("✅ Handlers registered")

    # Run both concurrently
    logger.info("✅ Launching bot + callback server together...")
    await asyncio.gather(
        run_bot(bot, dp),
        run_server()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Shutdown requested — bye!")