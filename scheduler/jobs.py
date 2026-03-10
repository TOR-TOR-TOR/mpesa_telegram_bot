"""
scheduler/jobs.py — Background jobs that run on a schedule.

Jobs:
  1. check_expiring_subscriptions — runs every 6 hours
     Sends reminders at 3 days and 1 day before expiry

  2. check_expired_subscriptions — runs every hour
     Deactivates expired subs and kicks users from channel
"""

import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from database import AsyncSessionLocal
from database.models import Subscription, User
from database.crud import deactivate_expired_subscriptions
import config

logger = logging.getLogger(__name__)

# Bot instance injected from main.py
_bot = None

def set_bot(bot_instance):
    """Inject bot so scheduler can send Telegram messages."""
    global _bot
    _bot = bot_instance


# ── Job 1: Expiry Reminders ───────────────────────────────────────────────────

async def check_expiring_subscriptions():
    """
    Runs every 6 hours.
    Sends a reminder if subscription expires in ~3 days or ~1 day.
    Uses reminder flags (reminded_3d, reminded_1d) to avoid duplicate messages.
    """
    logger.info("⏰ Running expiry reminder check...")
    now = datetime.utcnow()

    async with AsyncSessionLocal() as session:

        # Find all active subscriptions expiring within 4 days
        result = await session.execute(
            select(Subscription)
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at <= now + timedelta(days=4))
            .where(Subscription.expires_at > now)
        )
        expiring = result.scalars().all()

        for sub in expiring:
            days_left = (sub.expires_at - now).days

            # Fetch user
            user_result = await session.execute(
                select(User).where(User.id == sub.user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            # 3-day reminder
            if days_left <= 3 and not sub.reminded_3d:
                await _send_reminder(user, sub, days_left=3)
                sub.reminded_3d = True
                logger.info(f"📨 3-day reminder sent to {user.telegram_id}")

            # 1-day reminder
            elif days_left <= 1 and not sub.reminded_1d:
                await _send_reminder(user, sub, days_left=1)
                sub.reminded_1d = True
                logger.info(f"📨 1-day reminder sent to {user.telegram_id}")

        await session.commit()

    logger.info("✅ Expiry reminder check complete")


async def _send_reminder(user: User, sub: Subscription, days_left: int):
    """Send a renewal reminder message to the user."""
    if not _bot:
        return

    expiry_str = sub.expires_at.strftime("%d %b %Y")
    plan_label = config.PLANS.get(sub.plan, {}).get("label", sub.plan)

    if days_left <= 1:
        urgency = "⚠️ *Last chance!* Your subscription expires *tomorrow!*"
    else:
        urgency = f"📅 Your subscription expires in *{days_left} days*."

    try:
        await _bot.send_message(
            chat_id    = user.telegram_id,
            text       = (
                f"🔔 *Subscription Reminder*\n\n"
                f"{urgency}\n\n"
                f"📦 Plan: *{plan_label}*\n"
                f"📅 Expires: *{expiry_str}*\n\n"
                f"Renew now to keep your access:\n"
                f"/subscribe"
            ),
            parse_mode = "Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send reminder to {user.telegram_id}: {e}")


# ── Job 2: Expire and Kick ────────────────────────────────────────────────────

async def check_expired_subscriptions():
    """
    Runs every hour.
    Deactivates expired subscriptions and removes users from the channel.
    """
    logger.info("⏰ Running expiry check...")

    async with AsyncSessionLocal() as session:
        affected_user_ids = await deactivate_expired_subscriptions(session)

    if not affected_user_ids:
        logger.info("✅ No expired subscriptions found")
        return

    logger.info(f"🔒 Deactivating {len(affected_user_ids)} expired subscription(s)...")

    async with AsyncSessionLocal() as session:
        for user_id in affected_user_ids:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                continue

            # Kick from channel
            await _kick_from_channel(user)

            # Notify user
            await _notify_expired(user)

    logger.info("✅ Expiry check complete")


async def _kick_from_channel(user: User):
    """Remove user from the private channel."""
    if not _bot:
        return
    try:
        await _bot.ban_chat_member(
            chat_id = config.CHANNEL_ID,
            user_id = user.telegram_id
        )
        # Immediately unban so they can rejoin after resubscribing
        await _bot.unban_chat_member(
            chat_id          = config.CHANNEL_ID,
            user_id          = user.telegram_id,
            only_if_banned   = True
        )
        logger.info(f"🚪 Removed {user.telegram_id} from channel")
    except Exception as e:
        logger.warning(f"Could not remove {user.telegram_id} from channel: {e}")


async def _notify_expired(user: User):
    """Notify user their subscription has expired."""
    if not _bot:
        return
    try:
        await _bot.send_message(
            chat_id    = user.telegram_id,
            text       = (
                f"❌ *Subscription Expired*\n\n"
                f"Your subscription has ended and your channel access "
                f"has been removed.\n\n"
                f"Use /subscribe to renew and regain access instantly."
            ),
            parse_mode = "Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify expired user {user.telegram_id}: {e}")


# ── Scheduler Setup ───────────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the scheduler.
    Called once from main.py at startup.
    """
    scheduler = AsyncIOScheduler(timezone="Africa/Nairobi")

    # Check for expiring subs every 6 hours
    scheduler.add_job(
        check_expiring_subscriptions,
        trigger  = "interval",
        hours    = 6,
        id       = "expiry_reminders",
        name     = "Subscription expiry reminders",
        replace_existing = True
    )

    # Check for expired subs every hour
    scheduler.add_job(
        check_expired_subscriptions,
        trigger  = "interval",
        hours    = 1,
        id       = "expire_subscriptions",
        name     = "Expire and kick subscriptions",
        replace_existing = True
    )

    return scheduler