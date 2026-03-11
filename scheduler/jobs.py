"""
scheduler/jobs.py — Background jobs that run on a schedule.

Jobs:
  1. check_expiring_subscriptions — runs every 6 hours
  2. check_expired_subscriptions  — runs every hour
  3. cleanup_pending_transactions — runs every 30 minutes  ← Fix 3
"""

import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from database import AsyncSessionLocal
from database.models import Subscription, User, Transaction
from database.crud import deactivate_expired_subscriptions
import config

logger = logging.getLogger(__name__)

_bot = None

def set_bot(bot_instance):
    global _bot
    _bot = bot_instance


# ── Job 1: Expiry Reminders ───────────────────────────────────────────────────

async def check_expiring_subscriptions():
    """Runs every 6 hours. Sends reminders before expiry."""
    logger.info("⏰ Running expiry reminder check...")
    now = datetime.utcnow()
    reminded_count = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at <= now + timedelta(days=4))
            .where(Subscription.expires_at > now)
        )
        expiring = result.scalars().all()

        # Fix 7 — log how many were checked
        logger.info(f"📋 Found {len(expiring)} expiring subscription(s) to check")

        for sub in expiring:
            days_left = (sub.expires_at - now).days

            user_result = await session.execute(
                select(User).where(User.id == sub.user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            if days_left <= 3 and not sub.reminded_3d:
                await _send_reminder(user, sub, days_left=3)
                sub.reminded_3d = True
                reminded_count += 1
                logger.info(f"📨 3-day reminder sent to {user.telegram_id}")

            elif days_left <= 1 and not sub.reminded_1d:
                await _send_reminder(user, sub, days_left=1)
                sub.reminded_1d = True
                reminded_count += 1
                logger.info(f"📨 1-day reminder sent to {user.telegram_id}")

            else:
                logger.info(
                    f"⏭ Skipped reminder for {user.telegram_id} — "
                    f"days_left={days_left} "
                    f"reminded_3d={sub.reminded_3d} "
                    f"reminded_1d={sub.reminded_1d}"
                )

        await session.commit()

    logger.info(f"✅ Expiry reminder check complete — {reminded_count} reminder(s) sent")


async def _send_reminder(user: User, sub: Subscription, days_left: int):
    if not _bot:
        return

    expiry_str = sub.expires_at.strftime("%d %b %Y")
    plan_label = config.PLANS.get(sub.plan, {}).get("label", sub.plan)

    urgency = (
        "⚠️ Last chance! Your subscription expires tomorrow!"
        if days_left <= 1
        else f"📅 Your subscription expires in {days_left} days."
    )

    try:
        await _bot.send_message(
            chat_id = user.telegram_id,
            text    = (
                f"🔔 Subscription Reminder\n\n"
                f"{urgency}\n\n"
                f"📦 Plan: {plan_label}\n"
                f"📅 Expires: {expiry_str}\n\n"
                f"Renew now to keep your access:\n"
                f"/subscribe"
            )
        )
    except Exception as e:
        logger.error(f"Failed to send reminder to {user.telegram_id}: {e}")


# ── Job 2: Expire and Kick ────────────────────────────────────────────────────

async def check_expired_subscriptions():
    """Runs every hour. Deactivates expired subscriptions and removes users."""
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

            await _kick_from_channel(user)
            await _notify_expired(user)

    logger.info("✅ Expiry check complete")


async def _kick_from_channel(user: User):
    if not _bot:
        return
    try:
        # Fix 5 — skip if channel not configured
        if config.CHANNEL_ID == 0:
            logger.warning("Skipping kick — CHANNEL_ID not configured")
            return

        await _bot.ban_chat_member(
            chat_id = config.CHANNEL_ID,
            user_id = user.telegram_id
        )
        await _bot.unban_chat_member(
            chat_id        = config.CHANNEL_ID,
            user_id        = user.telegram_id,
            only_if_banned = True
        )
        logger.info(f"🚪 Removed {user.telegram_id} from channel")
    except Exception as e:
        logger.warning(f"Could not remove {user.telegram_id} from channel: {e}")


async def _notify_expired(user: User):
    if not _bot:
        return
    try:
        await _bot.send_message(
            chat_id = user.telegram_id,
            text    = (
                f"❌ Subscription Expired\n\n"
                f"Your subscription has ended and your channel access "
                f"has been removed.\n\n"
                f"Use /subscribe to renew and regain access instantly."
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify expired user {user.telegram_id}: {e}")


# ── Job 3: Cleanup Pending Transactions ──────────────────────────────────────

async def cleanup_pending_transactions():
    """
    Fix 3 — Runs every 30 minutes.
    Marks transactions as failed if they've been pending for more than 10 minutes.
    This handles cases where STK push timed out or callback never arrived.
    """
    logger.info("🧹 Running pending transaction cleanup...")
    cutoff = datetime.utcnow() - timedelta(minutes=10)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.status == "pending")
            .where(Transaction.created_at <= cutoff)
        )
        stale = result.scalars().all()

        if not stale:
            logger.info("✅ No stale pending transactions found")
            return

        for txn in stale:
            txn.status = "failed"
            logger.info(
                f"🗑 Marked stale transaction as failed | "
                f"ID: {txn.id} | CheckoutID: {txn.checkout_request_id}"
            )

        await session.commit()

    logger.info(f"✅ Cleaned up {len(stale)} stale pending transaction(s)")


# ── Scheduler Setup ───────────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Africa/Nairobi")

    scheduler.add_job(
        check_expiring_subscriptions,
        trigger          = "interval",
        hours            = 6,
        id               = "expiry_reminders",
        name             = "Subscription expiry reminders",
        replace_existing = True
    )

    scheduler.add_job(
        check_expired_subscriptions,
        trigger          = "interval",
        hours            = 1,
        id               = "expire_subscriptions",
        name             = "Expire and kick subscriptions",
        replace_existing = True
    )

    # Fix 3 — cleanup stale pending transactions every 30 minutes
    scheduler.add_job(
        cleanup_pending_transactions,
        trigger          = "interval",
        minutes          = 30,
        id               = "cleanup_pending",
        name             = "Cleanup stale pending transactions",
        replace_existing = True
    )

    return scheduler