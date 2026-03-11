"""
bot/handlers/admin.py — Admin-only commands.
All commands here are restricted to ADMIN_ID in config.

Commands:
  /admin         — show admin menu
  /stats         — revenue and subscriber stats
  /subscribers   — list all active subscribers
  /grant <id>    — manually grant access to a user
  /revoke <id>   — manually revoke access from a user
  /broadcast     — send a message to all active subscribers
"""

import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from database import AsyncSessionLocal
from database.models import User, Subscription, Transaction
from database.crud import create_subscription, get_active_subscription
from scheduler.jobs import _kick_from_channel, _notify_expired
import config

logger = logging.getLogger(__name__)
router = Router()


# ── Admin filter — blocks non-admins from all handlers in this router ─────────
from aiogram.filters import BaseFilter
from aiogram.types import Message

class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == config.ADMIN_ID

router.message.filter(IsAdmin())


# ── FSM for broadcast ─────────────────────────────────────────────────────────
class BroadcastState(StatesGroup):
    waiting_for_message = State()


# ── /admin ────────────────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Show admin command menu."""
    await message.answer(
        f"🛠 *Admin Panel — Kilima Bot*\n\n"
        f"Available commands:\n\n"
        f"/stats — Revenue and subscriber overview\n"
        f"/subscribers — List active subscribers\n"
        f"/grant `<telegram_id>` — Manually grant access\n"
        f"/revoke `<telegram_id>` — Manually revoke access\n"
        f"/broadcast — Message all active subscribers\n",
        parse_mode="Markdown"
    )


# ── /stats ────────────────────────────────────────────────────────────────────
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show revenue and subscriber statistics."""
    async with AsyncSessionLocal() as session:

        # Total active subscribers
        active_result = await session.execute(
            select(func.count(Subscription.id))
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at > datetime.utcnow())
        )
        active_count = active_result.scalar()

        # Total subscribers ever
        total_result = await session.execute(
            select(func.count(Subscription.id))
        )
        total_count = total_result.scalar()

        # Total successful transactions
        success_result = await session.execute(
            select(func.count(Transaction.id))
            .where(Transaction.status == "success")
        )
        success_count = success_result.scalar()

        # Total revenue
        revenue_result = await session.execute(
            select(func.sum(Transaction.amount))
            .where(Transaction.status == "success")
        )
        total_revenue = revenue_result.scalar() or 0

        # Per-plan breakdown
        plan_result = await session.execute(
            select(Subscription.plan, func.count(Subscription.id))
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at > datetime.utcnow())
            .group_by(Subscription.plan)
        )
        plan_breakdown = plan_result.all()

        # Total registered users
        users_result = await session.execute(
            select(func.count(User.id))
        )
        total_users = users_result.scalar()

    # Format plan breakdown
    plan_lines = ""
    for plan_id, count in plan_breakdown:
        label = config.PLANS.get(plan_id, {}).get("label", plan_id)
        plan_lines += f"  • {label}: {count} subscriber(s)\n"

    if not plan_lines:
        plan_lines = "  • No active subscriptions\n"

    await message.answer(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total registered users: *{total_users}*\n"
        f"✅ Active subscribers: *{active_count}*\n"
        f"📦 Total subscriptions ever: *{total_count}*\n"
        f"💳 Successful payments: *{success_count}*\n"
        f"💰 Total revenue: *KES {total_revenue}*\n\n"
        f"📋 *Active plan breakdown:*\n"
        f"{plan_lines}",
        parse_mode="Markdown"
    )


# ── /subscribers ──────────────────────────────────────────────────────────────
@router.message(Command("subscribers"))
async def cmd_subscribers(message: Message):
    """List all currently active subscribers."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at > datetime.utcnow())
            .order_by(Subscription.expires_at.asc())
        )
        rows = result.all()

    if not rows:
        await message.answer("📭 No active subscribers at the moment.")
        return

    lines = []
    for sub, user in rows:
        expiry   = sub.expires_at.strftime("%d %b %Y")
        plan     = config.PLANS.get(sub.plan, {}).get("label", sub.plan)
        name     = (user.full_name or "Unknown").replace("_", " ")
        username = f"@{user.username}" if user.username else str(user.telegram_id)

        lines.append(f"• {name} ({username})\n  {plan} — expires {expiry}")

    # Build plain text response — no Markdown to avoid parse errors
    header = f"👥 Active Subscribers ({len(rows)})\n\n"
    body   = "\n\n".join(lines)

    full_text = header + body

    # Chunk if over 4096 chars
    if len(full_text) <= 4096:
        await message.answer(full_text)
    else:
        chunk = header
        for line in lines:
            if len(chunk) + len(line) > 3900:
                await message.answer(chunk)
                chunk = ""
            chunk += line + "\n\n"
        if chunk:
            await message.answer(chunk)


# ── /grant ────────────────────────────────────────────────────────────────────
@router.message(Command("grant"))
async def cmd_grant(message: Message):
    """
    Manually grant a user access.
    Usage: /grant <telegram_id> <plan>
    Example: /grant 123456789 monthly
    """
    parts = message.text.strip().split()

    if len(parts) < 3:
        await message.answer(
            "❌ Usage: `/grant <telegram_id> <plan>`\n\n"
            "Plans: `weekly` | `monthly` | `quarterly`\n"
            "Example: `/grant 123456789 monthly`",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Invalid Telegram ID — must be a number.")
        return

    plan_id = parts[2].lower()
    plan    = config.PLANS.get(plan_id)

    if not plan:
        await message.answer(
            f"❌ Invalid plan `{plan_id}`.\n"
            f"Valid options: `weekly`, `monthly`, `quarterly`",
            parse_mode="Markdown"
        )
        return

    async with AsyncSessionLocal() as session:
        # Find or create user
        user_result = await session.execute(
            select(User).where(User.telegram_id == target_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            await message.answer(
                f"❌ User `{target_id}` not found.\n"
                f"They must start the bot first with /start.",
                parse_mode="Markdown"
            )
            return

        # Deactivate existing subscription
        existing = await get_active_subscription(session, user.id)
        if existing:
            existing.is_active = False
            await session.commit()

        # Grant new subscription
        sub = await create_subscription(
            session,
            user_id       = user.id,
            plan          = plan_id,
            duration_days = plan["duration_days"]
        )

    # Generate invite link
    try:
        invite = await message.bot.create_chat_invite_link(
            chat_id      = config.CHANNEL_ID,
            member_limit = 1
        )
        invite_link = invite.invite_link

        # Notify user
        await message.bot.send_message(
            chat_id    = target_id,
            text       = (
                f"🎁 *Access Granted!*\n\n"
                f"An admin has granted you a *{plan['label']}* subscription.\n"
                f"📅 Valid until: *{sub.expires_at.strftime('%d %b %Y')}*\n\n"
                f"👇 Click to join:\n{invite_link}"
            ),
            parse_mode = "Markdown"
        )

        await message.answer(
            f"✅ *Access granted*\n\n"
            f"User: `{target_id}`\n"
            f"Plan: *{plan['label']}*\n"
            f"Expires: *{sub.expires_at.strftime('%d %b %Y')}*",
            parse_mode="Markdown"
        )

    except Exception as e:
        await message.answer(f"✅ Subscription created but failed to notify user:\n`{e}`",
                             parse_mode="Markdown")


# ── /revoke ───────────────────────────────────────────────────────────────────
@router.message(Command("revoke"))
async def cmd_revoke(message: Message):
    """
    Manually revoke a user's access.
    Usage: /revoke <telegram_id>
    """
    parts = message.text.strip().split()

    if len(parts) < 2:
        await message.answer(
            "❌ Usage: `/revoke <telegram_id>`\n"
            "Example: `/revoke 123456789`",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Invalid Telegram ID — must be a number.")
        return

    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == target_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            await message.answer(f"❌ User `{target_id}` not found.", parse_mode="Markdown")
            return

        existing = await get_active_subscription(session, user.id)
        if not existing:
            await message.answer(
                f"❌ User `{target_id}` has no active subscription.",
                parse_mode="Markdown"
            )
            return

        existing.is_active = False
        await session.commit()

    # Kick from channel
    await _kick_from_channel(user)
    await _notify_expired(user)

    # Notify user
    try:
        await message.bot.send_message(
            chat_id    = target_id,
            text       = (
                f"❌ *Access Revoked*\n\n"
                f"Your subscription has been cancelled by an admin.\n"
                f"Contact support if you think this is a mistake.\n\n"
                f"Use /subscribe to get a new subscription."
            ),
            parse_mode = "Markdown"
        )
    except Exception:
        pass

    await message.answer(
        f"✅ Access revoked for user `{target_id}`.",
        parse_mode="Markdown"
    )


# ── /broadcast ────────────────────────────────────────────────────────────────
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Start broadcast flow — ask admin for message."""
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        "📢 *Broadcast Message*\n\n"
        "Type the message you want to send to all active subscribers.\n"
        "Supports Markdown formatting.\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown"
    )


@router.message(BroadcastState.waiting_for_message)
async def do_broadcast(message: Message, state: FSMContext):
    """Send broadcast to all active subscribers."""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Broadcast cancelled.")
        return

    broadcast_text = message.text
    await state.clear()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .join(Subscription, Subscription.user_id == User.id)
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at > datetime.utcnow())
        )
        users = result.scalars().all()

    if not users:
        await message.answer("📭 No active subscribers to broadcast to.")
        return

    sent = 0
    failed = 0

    status_msg = await message.answer(f"📤 Sending to {len(users)} subscribers...")

    for user in users:
        try:
            await message.bot.send_message(
                chat_id    = user.telegram_id,
                text       = f"📢 *Message from Admin:*\n\n{broadcast_text}",
                parse_mode = "Markdown"
            )
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Broadcast complete*\n\n"
        f"📨 Sent: *{sent}*\n"
        f"❌ Failed: *{failed}*",
        parse_mode="Markdown"
    )