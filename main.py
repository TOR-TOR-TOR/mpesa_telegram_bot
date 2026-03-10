"""
main.py — Single entry point.
Runs bot + callback server + scheduler together.
"""

import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import start, subscription, admin
from payments.callbacks import app as fastapi_app, set_bot
from scheduler.jobs import create_scheduler, set_bot as set_scheduler_bot
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
        log_level = "warning"
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    logger.info("🚀 Kilima Bot starting up...")

    # Initialize database
    await init_db()
    logger.info("✅ Database ready")

    # Create bot and dispatcher
    bot = Bot(token=config.BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    # Inject bot into callback server and scheduler
    set_bot(bot)
    set_scheduler_bot(bot)
    logger.info("✅ Bot injected into callback server and scheduler")

    # Register handlers
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)
    logger.info("✅ Handlers registered")

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("✅ Scheduler started — jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"   • {job.name} — next run: {job.next_run_time}")

    # Run bot + callback server together
    logger.info("✅ Launching bot + callback server...")
    try:
        await asyncio.gather(
            run_bot(bot, dp),
            run_server()
        )
    finally:
        scheduler.shutdown()
        logger.info("👋 Scheduler stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Shutdown requested — bye!")