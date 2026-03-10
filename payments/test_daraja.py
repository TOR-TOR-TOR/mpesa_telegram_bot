"""
payments/test_daraja.py — Run this to verify Daraja sandbox is working.
DELETE or exclude this file before going to production.

Usage:
    python -m payments.test_daraja
"""

import asyncio
import httpx
from payments.daraja import get_access_token, stk_push, format_phone


async def test_auth():
    print("\n── Test 1: OAuth Token ───────────────────────")
    try:
        token = await get_access_token()
        print(f"✅ Token received: {token[:30]}...")
    except Exception as e:
        print(f"❌ Auth failed: {e}")


async def test_phone_formatter():
    print("\n── Test 2: Phone Formatter ───────────────────")
    test_cases = [
        ("0712345678",    "254712345678"),
        ("+254712345678", "254712345678"),
        ("254712345678",  "254712345678"),
    ]
    for input_num, expected in test_cases:
        result = format_phone(input_num)
        status = "✅" if result == expected else "❌"
        print(f"{status}  {input_num} → {result}")


async def test_stk_push():
    print("\n── Test 3: STK Push ──────────────────────────")
    print("⚠️  This will send a REAL prompt to the phone number below.")
    print("    Using Daraja sandbox — no actual money is charged.\n")

    # ← Replace with your real Safaricom number
    test_phone = "0742132094"

    try:
        formatted = format_phone(test_phone)
        result = await stk_push(
            phone_number = formatted,
            amount       = 1,
            account_ref  = "TestPayment",
            description  = "Subscription Test"
        )
        print(f"✅ STK Push sent successfully!")
        print(f"   CheckoutRequestID  : {result.get('CheckoutRequestID')}")
        print(f"   ResponseDescription: {result.get('ResponseDescription')}")
        print(f"   CustomerMessage    : {result.get('CustomerMessage')}")
    except httpx.ConnectTimeout:
        print("❌ ConnectTimeout — could not reach Daraja. Check your internet.")
    except httpx.ReadTimeout:
        print("❌ ReadTimeout — request sent but no response. Try again.")
    except Exception as e:
        print(f"❌ STK Push failed: {e}")


async def main():
    print("═══════════════════════════════════════════════")
    print("   Daraja API — Sandbox Connection Tests")
    print("═══════════════════════════════════════════════")
    await test_auth()
    await test_phone_formatter()
    await test_stk_push()
    print("\n═══════════════════════════════════════════════\n")


if __name__ == "__main__":
    asyncio.run(main())