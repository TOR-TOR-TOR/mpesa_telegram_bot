"""
payments/daraja.py — Safaricom Daraja API client.
Handles authentication and STK Push initiation.
"""

import base64
import httpx
from datetime import datetime
import config


def _generate_password() -> tuple[str, str]:
    """
    Generate the M-Pesa API password and timestamp.
    Password = Base64(Shortcode + Passkey + Timestamp)
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{config.MPESA_SHORTCODE}{config.MPESA_PASSKEY}{timestamp}"
    password = base64.b64encode(raw.encode()).decode()
    return password, timestamp


async def get_access_token() -> str:
    """
    Fetch a fresh OAuth token from Daraja.
    Tokens expire after 1 hour — we fetch a new one per request for simplicity.
    """
    url = f"{config.DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            auth=(config.MPESA_CONSUMER_KEY, config.MPESA_CONSUMER_SECRET)
        )

    if response.status_code != 200:
        raise Exception(
            f"Daraja auth failed: {response.status_code} — {response.text}"
        )

    return response.json()["access_token"]


async def stk_push(phone_number: str, amount: int,
                   account_ref: str, description: str) -> dict:
    """
    Initiate an STK Push — sends a payment prompt to the user's phone.

    Args:
        phone_number: In format 2547XXXXXXXX (no + sign)
        amount:       Amount in KES (whole numbers only)
        account_ref:  Short reference shown on M-Pesa (e.g. 'WeeklyPlan')
        description:  Transaction description shown on M-Pesa receipt

    Returns:
        Daraja response dict containing CheckoutRequestID on success
    """
    token = await get_access_token()
    password, timestamp = _generate_password()

    url = f"{config.DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest"

    payload = {
        "BusinessShortCode": config.MPESA_SHORTCODE,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone_number,
        "PartyB":            config.MPESA_SHORTCODE,
        "PhoneNumber":       phone_number,
        "CallBackURL":       config.MPESA_CALLBACK_URL,
        "AccountReference":  account_ref,
        "TransactionDesc":   description,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )

    # Handle non-200 HTTP responses (e.g. 503 Service Unavailable)
    if response.status_code != 200:
        raise Exception(
            f"Daraja returned HTTP {response.status_code} — "
            f"sandbox may be temporarily down. Try again in a moment."
        )

    data = response.json()

    if data.get("ResponseCode") != "0":
        raise Exception(
            f"STK Push failed: {data.get('ResponseCode')} — "
            f"{data.get('ResponseDescription', 'Unknown error')}"
        )

    return data


def format_phone(phone: str) -> str:
    """
    Normalize a Kenyan phone number to 2547XXXXXXXX format.

    Accepts:
        0712345678   → 254712345678
        +254712345678 → 254712345678
        254712345678  → 254712345678
    """
    phone = phone.strip().replace(" ", "").replace("-", "")

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("0"):
        phone = "254" + phone[1:]

    if not phone.startswith("254"):
        raise ValueError(
            f"Invalid Kenyan phone number: {phone}. "
            f"Must start with 07, +254, or 254."
        )

    if len(phone) != 12:
        raise ValueError(
            f"Phone number {phone} has {len(phone)} digits — expected 12."
        )

    return phone