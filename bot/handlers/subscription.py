"""
bot/handlers/subscription.py — Subscription flow handlers.
Handles plan selection, phone number collection, and payment confirmation.
"""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import AsyncSessionLocal
from database.crud import get_or_create_user, get_active_subscription
from bot.keyboards import plans_keyboard, confirm_payment_keyboard
import config

logger = logging.getLogger(__name__)
router = Router()


# ── FSM States ────────────────────────────────────────────────────────────────
class SubscriptionStates(StatesGroup):
    waiting_for_phone   = State()   # user needs to enter their phone number
    waiting_for_confirm = State()   # user needs to confirm payment details


# ── /subscribe command ────────────────────────────────────────────────────────
@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, state: FSMContext):
    """Show available subscription plans."""
    await state.clear()

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
            f"✅ You already have an active *{active_sub.plan.title()}* "
            f"subscription until *{expiry}*.\n\n"
            f"You can still subscribe below to renew or upgrade:",
            parse_mode="Markdown",
            reply_markup=plans_keyboard()
        )
    else:
        await message.answer(
            f"💳 *Choose a Subscription Plan*\n\n"
            f"Select the plan that works best for you:",
            parse_mode="Markdown",
            reply_markup=plans_keyboard()
        )


# ── Plan selected ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("plan:"))
async def on_plan_selected(callback: CallbackQuery, state: FSMContext):
    """User selected a plan — ask for their phone number."""
    plan_id = callback.data.split(":")[1]
    plan    = config.PLANS.get(plan_id)

    if not plan:
        await callback.answer("Invalid plan. Please try again.")
        return

    # Store selected plan in FSM state
    await state.update_data(selected_plan=plan_id)
    await state.set_state(SubscriptionStates.waiting_for_phone)

    await callback.message.edit_text(
        f"📦 *{plan['label']} Plan — KES {plan['price']}*\n"
        f"_{plan['description']}_\n\n"
        f"📱 Please enter your *M-Pesa phone number*:\n"
        f"_(Format: 07XXXXXXXX or 01XXXXXXXX)_",
        parse_mode="Markdown"
    )
    await callback.answer()


# ── Phone number received ─────────────────────────────────────────────────────
@router.message(SubscriptionStates.waiting_for_phone)
async def on_phone_received(message: Message, state: FSMContext):
    """Validate phone number and ask for confirmation."""
    from payments.daraja import format_phone

    raw_phone = message.text.strip()

    # Validate phone number
    try:
        formatted_phone = format_phone(raw_phone)
    except ValueError as e:
        await message.answer(
            f"❌ *Invalid phone number*\n\n"
            f"{e}\n\n"
            f"Please enter a valid Safaricom number (e.g. 0712345678):",
            parse_mode="Markdown"
        )
        return

    # Store phone in FSM state
    data    = await state.get_data()
    plan_id = data.get("selected_plan")
    plan    = config.PLANS.get(plan_id)

    await state.update_data(phone=formatted_phone)
    await state.set_state(SubscriptionStates.waiting_for_confirm)

    await message.answer(
        f"📋 *Confirm Payment Details*\n\n"
        f"📦 Plan: *{plan['label']}*\n"
        f"💰 Amount: *KES {plan['price']}*\n"
        f"📱 Phone: *{raw_phone}*\n"
        f"⏳ Duration: *{plan['description']}*\n\n"
        f"An M-Pesa STK push will be sent to your phone.\n"
        f"Enter your PIN when prompted.",
        parse_mode="Markdown",
        reply_markup=confirm_payment_keyboard(plan_id)
    )


# ── Payment confirmed ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("confirm:"))
async def on_payment_confirmed(callback: CallbackQuery, state: FSMContext):
    """User confirmed — trigger STK Push."""
    from payments.daraja import stk_push
    from database.crud import update_user_phone, create_transaction
    import httpx

    data        = await state.get_data()
    phone       = data.get("phone")
    plan_id     = callback.data.split(":")[1]
    plan        = config.PLANS.get(plan_id)

    if not phone or not plan:
        await callback.answer("Session expired. Please use /subscribe again.")
        await state.clear()
        return

    await callback.message.edit_text(
        f"⏳ *Sending M-Pesa prompt...*\n\n"
        f"Please wait while we send the STK push to your phone.",
        parse_mode="Markdown"
    )

    try:
        # Save phone number to user profile
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(
                session,
                telegram_id = callback.from_user.id,
                username    = callback.from_user.username,
                full_name   = callback.from_user.full_name
            )
            await update_user_phone(session, callback.from_user.id, phone)

        # Trigger STK Push
        result = await stk_push(
            phone_number = phone,
            amount       = plan["price"],
            account_ref  = plan["label"].replace(" ", ""),
            description  = f"{plan['label']} Subscription"
        )

        checkout_request_id = result.get("CheckoutRequestID")

        # Record transaction as pending
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(
                session,
                telegram_id = callback.from_user.id
            )
            await create_transaction(
                session,
                user_id             = user.id,
                plan                = plan_id,
                amount              = plan["price"],
                phone_number        = phone,
                checkout_request_id = checkout_request_id
            )

        await callback.message.edit_text(
            f"📲 *M-Pesa Prompt Sent!*\n\n"
            f"Check your phone and enter your M-Pesa PIN to complete payment.\n\n"
            f"💰 Amount: *KES {plan['price']}*\n"
            f"📱 Phone: *{phone}*\n\n"
            f"_You have 60 seconds to complete the payment._",
            parse_mode="Markdown"
        )

    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        await callback.message.edit_text(
            f"⚠️ *Request timed out*\n\n"
            f"The M-Pesa server took too long to respond. Please try again.",
            parse_mode="Markdown",
            reply_markup=confirm_payment_keyboard(plan_id)
        )
    except Exception as e:
        logger.error(f"STK Push error for {callback.from_user.id}: {e}")
        await callback.message.edit_text(
            f"❌ *Payment initiation failed*\n\n"
            f"Something went wrong. Please try /subscribe again.",
            parse_mode="Markdown"
        )

    await state.clear()
    await callback.answer()


# ── Cancel ────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext):
    """User cancelled the flow."""
    await state.clear()
    await callback.message.edit_text(
        "❌ *Cancelled.*\n\nUse /subscribe whenever you're ready.",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "try_again")
async def on_try_again(callback: CallbackQuery, state: FSMContext):
    """Redirect user back to plan selection."""
    await state.clear()
    await callback.message.edit_text(
        f"💳 *Choose a Subscription Plan*\n\n"
        f"Select the plan that works best for you:",
        parse_mode="Markdown",
        reply_markup=plans_keyboard()
    )
    await callback.answer()