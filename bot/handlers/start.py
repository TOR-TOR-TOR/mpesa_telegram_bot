"""
bot/handlers/start.py — /start and /help command handlers.
"""

import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from database import AsyncSessionLocal
from database.crud import get_or_create_user, get_active_subscription

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Welcome message when user first starts the bot."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id = message.from_user.id,
            username    = message.from_user.username,
            full_name   = message.from_user.full_name
        )
        active_sub = await get_active_subscription(session, user.id)

    if active_sub:
        expiry = active_sub.expires_at.strftime("%d %b %Y")
        await message.answer(
            f"👋 Welcome back, *{message.from_user.first_name}!*\n\n"
            f"✅ You have an active *{active_sub.plan.title()}* subscription.\n"
            f"📅 Expires on: *{expiry}*\n\n"
            f"Use /status to check your subscription details.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"👋 Welcome, *{message.from_user.first_name}!*\n\n"
            f"This bot gives you access to our exclusive members channel "
            f"via M-Pesa payment.\n\n"
            f"💳 Use /subscribe to view available plans and get started.\n"
            f"📋 Use /status to check your subscription status.",
            parse_mode="Markdown"
        )


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Check current subscription status."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id = message.from_user.id,
            username    = message.from_user.username,
            full_name   = message.from_user.full_name
        )
        active_sub = await get_active_subscription(session, user.id)

    if active_sub:
        expiry  = active_sub.expires_at.strftime("%d %b %Y at %H:%M UTC")
        started = active_sub.started_at.strftime("%d %b %Y")
        await message.answer(
            f"📋 *Your Subscription Status*\n\n"
            f"✅ Status: *Active*\n"
            f"📦 Plan: *{active_sub.plan.title()}*\n"
            f"📅 Started: *{started}*\n"
            f"⏳ Expires: *{expiry}*\n\n"
            f"Use /subscribe to renew or upgrade your plan.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"📋 *Your Subscription Status*\n\n"
            f"❌ Status: *No active subscription*\n\n"
            f"Use /subscribe to get access.",
            parse_mode="Markdown"
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """List available commands."""
    await message.answer(
        f"🤖 *Available Commands*\n\n"
        f"/start — Welcome message\n"
        f"/subscribe — View plans and subscribe\n"
        f"/status — Check your subscription status\n"
        f"/help — Show this help message\n\n"
        f"💬 For support, contact @yoursupporthandle",
        parse_mode="Markdown"
    )

@router.message(Command("id"))
async def cmd_id(message: Message):
    """Fix 6 — Let users find their Telegram ID."""
    await message.answer(
        f"Your Telegram ID is: {message.from_user.id}"
    )