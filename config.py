"""
config.py — Central configuration loader.
All environment variables are read once here.
Every other module imports from this file — never from os.environ directly.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Read an env var and raise a clear error if it's missing."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"\n\n  Missing required environment variable: {key}\n"
            f"  → Copy .env.example to .env and fill in your values.\n"
        )
    return value


# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str       = _require("BOT_TOKEN")
CHANNEL_ID: int      = int(_require("CHANNEL_ID"))
ADMIN_ID: int        = int(_require("ADMIN_ID"))

# ── M-Pesa / Daraja ───────────────────────────────────────────────────────────
MPESA_CONSUMER_KEY:    str = _require("MPESA_CONSUMER_KEY")
MPESA_CONSUMER_SECRET: str = _require("MPESA_CONSUMER_SECRET")
MPESA_SHORTCODE:       str = _require("MPESA_SHORTCODE")
MPESA_PASSKEY:         str = _require("MPESA_PASSKEY")
MPESA_ENV:             str = os.getenv("MPESA_ENV", "sandbox")
CALLBACK_BASE_URL:     str = _require("CALLBACK_BASE_URL").rstrip("/")

# Derived: Daraja base URL switches automatically based on MPESA_ENV
DARAJA_BASE_URL: str = (
    "https://sandbox.safaricom.co.ke"
    if MPESA_ENV == "sandbox"
    else "https://api.safaricom.co.ke"
)

# The full callback URL Daraja will POST payment results to
MPESA_CALLBACK_URL: str = f"{CALLBACK_BASE_URL}/payments/callback"

# ── App ───────────────────────────────────────────────────────────────────────
PORT:         int = int(os.getenv("PORT", "8000"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./subscriptions.db")

# ── Subscription Plans ────────────────────────────────────────────────────────
PLANS: dict = {
    "weekly": {
        "label":         "Weekly",
        "price":         1,
        "duration_days": 7,
        "description":   "7-day access",
    },
    "monthly": {
        "label":         "Monthly",
        "price":         2,
        "duration_days": 30,
        "description":   "30-day access",
    },
    "quarterly": {
        "label":         "Quarterly",
        "price":         3,
        "duration_days": 90,
        "description":   "90-day access — best value",
    },
}