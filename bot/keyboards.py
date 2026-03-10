"""
bot/keyboards.py — All inline and reply keyboards used by the bot.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config


def plans_keyboard() -> InlineKeyboardMarkup:
    """Subscription plan selection keyboard."""
    builder = InlineKeyboardBuilder()

    for plan_id, plan in config.PLANS.items():
        builder.add(InlineKeyboardButton(
            text=f"{plan['label']} — KES {plan['price']} ({plan['description']})",
            callback_data=f"plan:{plan_id}"
        ))

    builder.add(InlineKeyboardButton(
        text="❌ Cancel",
        callback_data="cancel"
    ))

    builder.adjust(1)  # one button per row
    return builder.as_markup()


def confirm_payment_keyboard(plan_id: str) -> InlineKeyboardMarkup:
    """Confirm or cancel payment keyboard."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Yes, send me the prompt",
        callback_data=f"confirm:{plan_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Cancel",
        callback_data="cancel"
    ))
    builder.adjust(1)
    return builder.as_markup()


def try_again_keyboard() -> InlineKeyboardMarkup:
    """Shown after a failed payment."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="🔄 Try Again",
        callback_data="try_again"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Cancel",
        callback_data="cancel"
    ))
    builder.adjust(1)
    return builder.as_markup()