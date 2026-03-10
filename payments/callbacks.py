"""
payments/callbacks.py — FastAPI server that receives M-Pesa payment callbacks.
Daraja POSTs to /payments/callback after every STK Push attempt.
"""

import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from database import AsyncSessionLocal, init_db
from database.crud import (
    update_transaction_status,
    create_subscription,
    get_active_subscription
)
from database.models import Transaction, User
from sqlalchemy import select
import config

logger = logging.getLogger(__name__)

app = FastAPI()

_bot = None

def set_bot(bot_instance):
    """Called from main.py to inject the bot into this module."""
    global _bot
    _bot = bot_instance


@app.on_event("startup")
async def startup():
    """Initialize database tables when server starts."""
    await init_db()
    logger.info("✅ Callback server started — DB initialized")


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "mpesa-callback-server"}


@app.post("/payments/callback")
async def mpesa_callback(request: Request):
    try:
        body = await request.json()
        logger.info(f"📩 Callback received: {body}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        stk_callback = body["Body"]["stkCallback"]
    except KeyError:
        raise HTTPException(status_code=400, detail="Missing stkCallback in payload")

    checkout_request_id = stk_callback.get("CheckoutRequestID")
    result_code         = stk_callback.get("ResultCode")
    result_desc         = stk_callback.get("ResultDesc", "")

    if not checkout_request_id:
        raise HTTPException(status_code=400, detail="Missing CheckoutRequestID")

    async with AsyncSessionLocal() as session:

        # ── Payment Failed ────────────────────────────────────────────────────
        if result_code != 0:
            logger.warning(f"❌ Payment failed: {result_desc} | ID: {checkout_request_id}")

            txn = await update_transaction_status(
                session, checkout_request_id, status="failed"
            )

            if txn and _bot:
                await _notify_user_failed(txn, result_desc)

            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # ── Payment Successful ────────────────────────────────────────────────
        metadata      = stk_callback.get("CallbackMetadata", {}).get("Item", [])
        meta_dict     = {item["Name"]: item.get("Value") for item in metadata}

        amount        = meta_dict.get("Amount")
        mpesa_receipt = meta_dict.get("MpesaReceiptNumber")
        phone         = meta_dict.get("PhoneNumber")

        logger.info(
            f"✅ Payment success | Receipt: {mpesa_receipt} | "
            f"Amount: {amount} | Phone: {phone}"
        )

        # ── Fetch transaction first before any other logic ────────────────────
        txn_result = await session.execute(
            select(Transaction).where(
                Transaction.checkout_request_id == checkout_request_id
            )
        )
        txn = txn_result.scalar_one_or_none()

        if not txn:
            logger.error(f"Transaction not found for ID: {checkout_request_id}")
            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # Update transaction to success
        txn.status        = "success"
        txn.mpesa_receipt = str(mpesa_receipt) if mpesa_receipt else None
        await session.commit()

        # ── Fetch the user ────────────────────────────────────────────────────
        result = await session.execute(
            select(User).where(User.id == txn.user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found for transaction: {txn.id}")
            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # ── Block: check if user already has an active subscription ──────────
        existing = await get_active_subscription(session, user.id)
        if existing:
            expiry_str = existing.expires_at.strftime("%d %b %Y")
            plan_label = config.PLANS.get(existing.plan, {}).get("label", existing.plan)

            logger.warning(
                f"⚠️ Duplicate payment blocked | User: {user.telegram_id} | "
                f"Existing plan: {existing.plan} | Expires: {existing.expires_at}"
            )

            # Notify user
            if _bot:
                try:
                    await _bot.send_message(
                        chat_id = user.telegram_id,
                        text    = (
                            f"⚠️ Duplicate Payment Detected\n\n"
                            f"You already have an active {plan_label} subscription "
                            f"valid until {expiry_str}.\n\n"
                            f"Your payment of KES {amount} "
                            f"(Receipt: {mpesa_receipt}) "
                            f"has been received but will be refunded.\n\n"
                            f"Please contact support if you need help.\n"
                            f"Your current access remains active."
                        )
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user of duplicate: {e}")

            # Notify admin
            if _bot:
                try:
                    await _bot.send_message(
                        chat_id = config.ADMIN_ID,
                        text    = (
                            f"⚠️ Duplicate Payment Alert\n\n"
                            f"User: {user.full_name} ({user.telegram_id})\n"
                            f"Receipt: {mpesa_receipt}\n"
                            f"Amount: KES {amount}\n"
                            f"Existing plan: {plan_label} until {expiry_str}\n\n"
                            f"Please process a refund for this user."
                        )
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin of duplicate: {e}")

            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # ── No existing subscription — create new one ─────────────────────────
        plan_config = config.PLANS.get(txn.plan, {})
        duration    = plan_config.get("duration_days", 30)

        sub = await create_subscription(
            session,
            user_id       = user.id,
            plan          = txn.plan,
            duration_days = duration
        )

        logger.info(
            f"🎉 Subscription created | User: {user.telegram_id} | "
            f"Plan: {txn.plan} | Expires: {sub.expires_at}"
        )

        if _bot:
            await _grant_access_and_notify(user, txn, sub, mpesa_receipt)

    return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


async def _grant_access_and_notify(user, txn, sub, mpesa_receipt):
    """Generate invite link and notify user of successful payment."""
    try:
        invite = await _bot.create_chat_invite_link(
            chat_id      = config.CHANNEL_ID,
            member_limit = 1
        )

        expiry_str = sub.expires_at.strftime("%d %b %Y")
        plan_label = config.PLANS.get(txn.plan, {}).get("label", txn.plan)

        message = (
            f"✅ Payment Confirmed!\n\n"
            f"🧾 Receipt: {mpesa_receipt}\n"
            f"📦 Plan: {plan_label}\n"
            f"📅 Access until: {expiry_str}\n\n"
            f"👇 Click below to join the channel:\n"
            f"{invite.invite_link}\n\n"
            f"This link is single-use. Do not share it."
        )

        await _bot.send_message(
            chat_id = user.telegram_id,
            text    = message
        )

    except Exception as e:
        logger.error(f"Failed to grant access to {user.telegram_id}: {e}")


async def _notify_user_failed(txn, reason: str):
    """Notify user their payment failed."""
    try:
        reason_map = {
            "1032": "You cancelled the payment request.",
            "1037": "Request timed out — please try again.",
            "2001": "Wrong PIN entered — please try again.",
        }

        friendly = next(
            (msg for code, msg in reason_map.items() if code in str(reason)),
            "Your payment could not be completed. Please try again."
        )

        await _bot.send_message(
            chat_id = txn.user_id,
            text    = (
                f"❌ Payment Failed\n\n"
                f"{friendly}\n\n"
                f"Type /subscribe to try again."
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify user of failed payment: {e}")