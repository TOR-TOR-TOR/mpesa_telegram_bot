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

# Bot instance injected at startup from main.py
# We need it here to send Telegram notifications after payment
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
    """
    Main M-Pesa callback endpoint.
    Daraja POSTs here after every STK Push attempt (success or failure).

    Expected payload structure from Daraja:
    {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "...",
                "CheckoutRequestID": "ws_CO_...",
                "ResultCode": 0,         ← 0 = success, anything else = failed
                "ResultDesc": "...",
                "CallbackMetadata": {    ← only present on success
                    "Item": [
                        {"Name": "Amount", "Value": 1.0},
                        {"Name": "MpesaReceiptNumber", "Value": "ABC123"},
                        {"Name": "PhoneNumber", "Value": 254712345678}
                    ]
                }
            }
        }
    }
    """
    try:
        body = await request.json()
        logger.info(f"📩 Callback received: {body}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Navigate to the callback data
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

            # Notify user their payment failed
            if txn and _bot:
                await _notify_user_failed(txn, result_desc)

            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # ── Payment Successful ────────────────────────────────────────────────
        # Extract metadata from callback
        metadata    = stk_callback.get("CallbackMetadata", {}).get("Item", [])
        meta_dict   = {item["Name"]: item.get("Value") for item in metadata}

        amount          = meta_dict.get("Amount")
        mpesa_receipt   = meta_dict.get("MpesaReceiptNumber")
        phone           = meta_dict.get("PhoneNumber")

        logger.info(
            f"✅ Payment success | Receipt: {mpesa_receipt} | "
            f"Amount: {amount} | Phone: {phone}"
        )

        # Update transaction to success
        txn = await update_transaction_status(
            session,
            checkout_request_id,
            status="success",
            mpesa_receipt=str(mpesa_receipt) if mpesa_receipt else None
        )

        if not txn:
            logger.error(f"Transaction not found for ID: {checkout_request_id}")
            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # Fetch the user
        result  = await session.execute(
            select(User).where(User.id == txn.user_id)
        )
        user    = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found for transaction: {txn.id}")
            return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        # Deactivate any existing subscription first
        existing = await get_active_subscription(session, user.id)
        if existing:
            existing.is_active = False
            await session.commit()

        # Create new subscription
        plan_config = config.PLANS.get(txn.plan, {})
        duration    = plan_config.get("duration_days", 30)

        sub = await create_subscription(
            session,
            user_id      = user.id,
            plan         = txn.plan,
            duration_days= duration
        )

        logger.info(
            f"🎉 Subscription created | User: {user.telegram_id} | "
            f"Plan: {txn.plan} | Expires: {sub.expires_at}"
        )

        # Grant channel access and notify user
        if _bot:
            await _grant_access_and_notify(user, txn, sub, mpesa_receipt)

    # Always return 200 to Daraja — if we return anything else
    # Daraja will keep retrying the callback
    return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


async def _grant_access_and_notify(user, txn, sub, mpesa_receipt):
    """Generate invite link and notify user of successful payment."""
    try:
        # Generate a one-time invite link to the private channel
        invite = await _bot.create_chat_invite_link(
            chat_id     = config.CHANNEL_ID,
            member_limit= 1       # single use
        )

        expiry_str = sub.expires_at.strftime("%d %b %Y")
        plan_label = config.PLANS.get(txn.plan, {}).get("label", txn.plan)

        message = (
            f"✅ *Payment Confirmed!*\n\n"
            f"🧾 Receipt: `{mpesa_receipt}`\n"
            f"📦 Plan: *{plan_label}*\n"
            f"📅 Access until: *{expiry_str}*\n\n"
            f"👇 Click below to join the channel:\n"
            f"{invite.invite_link}\n\n"
            f"_This link is single-use. Do not share it._"
        )

        await _bot.send_message(
            chat_id    = user.telegram_id,
            text       = message,
            parse_mode = "Markdown"
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

        # Extract code from reason string if present
        friendly = next(
            (msg for code, msg in reason_map.items() if code in str(reason)),
            "Your payment could not be completed. Please try again."
        )

        await _bot.send_message(
            chat_id    = txn.user_id,
            text       = (
                f"❌ *Payment Failed*\n\n"
                f"{friendly}\n\n"
                f"Type /subscribe to try again."
            ),
            parse_mode = "Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify user of failed payment: {e}")