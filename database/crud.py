"""
database/crud.py — All database read/write operations.
Bot and payment modules call these functions, never raw SQL.
"""

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import User, Subscription, Transaction


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_or_create_user(session: AsyncSession, telegram_id: int,
                              username: str = None, full_name: str = None) -> User:
    """Fetch existing user or create a new one."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def update_user_phone(session: AsyncSession,
                             telegram_id: int, phone: str) -> None:
    """Save M-Pesa phone number against a user."""
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(phone_number=phone)
    )
    await session.commit()


# ── Subscriptions ─────────────────────────────────────────────────────────────

async def get_active_subscription(session: AsyncSession,
                                   user_id: int) -> Subscription | None:
    """Return the user's current active subscription, or None."""
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.is_active == True)
        .where(Subscription.expires_at > datetime.utcnow())
    )
    return result.scalar_one_or_none()


async def create_subscription(session: AsyncSession, user_id: int,
                               plan: str, duration_days: int) -> Subscription:
    """Activate a new subscription for a user."""
    now = datetime.utcnow()
    sub = Subscription(
        user_id    = user_id,
        plan       = plan,
        is_active  = True,
        started_at = now,
        expires_at = now + timedelta(days=duration_days)
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def deactivate_expired_subscriptions(session: AsyncSession) -> list:
    """Find and deactivate all expired subscriptions. Returns list of affected user_ids."""
    result = await session.execute(
        select(Subscription)
        .where(Subscription.is_active == True)
        .where(Subscription.expires_at <= datetime.utcnow())
    )
    expired = result.scalars().all()

    affected_user_ids = []
    for sub in expired:
        sub.is_active = False
        affected_user_ids.append(sub.user_id)

    await session.commit()
    return affected_user_ids


# ── Transactions ──────────────────────────────────────────────────────────────

async def create_transaction(session: AsyncSession, user_id: int, plan: str,
                              amount: int, phone_number: str,
                              checkout_request_id: str) -> Transaction:
    """Record a new pending transaction when STK push is sent."""
    txn = Transaction(
        user_id             = user_id,
        plan                = plan,
        amount              = amount,
        phone_number        = phone_number,
        checkout_request_id = checkout_request_id,
        status              = "pending"
    )
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return txn


async def update_transaction_status(session: AsyncSession, checkout_request_id: str,
                                     status: str, mpesa_receipt: str = None) -> Transaction | None:
    """Update transaction status when Daraja callback arrives."""
    result = await session.execute(
        select(Transaction)
        .where(Transaction.checkout_request_id == checkout_request_id)
    )
    txn = result.scalar_one_or_none()

    if txn:
        txn.status       = status
        txn.updated_at   = datetime.utcnow()
        if mpesa_receipt:
            txn.mpesa_receipt = mpesa_receipt
        await session.commit()

    return txn