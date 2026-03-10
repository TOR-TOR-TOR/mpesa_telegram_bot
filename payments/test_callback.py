"""
payments/test_callback.py — Test the callback server starts and responds.
Usage:
    python -m payments.test_callback
"""

import asyncio
import httpx


async def test_health():
    print("\n── Test: Callback Server Health ──────────────")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("http://localhost:8000/health")
        if r.status_code == 200:
            print(f"✅ Server is running: {r.json()}")
        else:
            print(f"❌ Unexpected status: {r.status_code}")
    except httpx.ConnectError:
        print("❌ Server not running — start it first with:")
        print("   uvicorn payments.callbacks:app --port 8000 --reload")


async def test_simulate_success_callback():
    """Simulate a successful M-Pesa callback from Daraja."""
    print("\n── Test: Simulate Successful Payment ─────────")
    payload = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "test-merchant-123",
                "CheckoutRequestID": "ws_CO_TEST_SIMULATE_001",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount",             "Value": 150.0},
                        {"Name": "MpesaReceiptNumber", "Value": "TEST123ABC"},
                        {"Name": "PhoneNumber",        "Value": 254712345678}
                    ]
                }
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "http://localhost:8000/payments/callback",
                json=payload
            )
        print(f"✅ Response: {r.status_code} — {r.json()}")
    except httpx.ConnectError:
        print("❌ Server not running.")


async def test_simulate_failed_callback():
    """Simulate a cancelled/failed M-Pesa callback."""
    print("\n── Test: Simulate Failed Payment ─────────────")
    payload = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "test-merchant-456",
                "CheckoutRequestID": "ws_CO_TEST_SIMULATE_002",
                "ResultCode": 1032,
                "ResultDesc": "Request cancelled by user."
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "http://localhost:8000/payments/callback",
                json=payload
            )
        print(f"✅ Response: {r.status_code} — {r.json()}")
    except httpx.ConnectError:
        print("❌ Server not running.")


async def main():
    print("═══════════════════════════════════════════════")
    print("   Callback Server Tests")
    print("═══════════════════════════════════════════════")
    await test_health()
    await test_simulate_success_callback()
    await test_simulate_failed_callback()
    print("\n═══════════════════════════════════════════════\n")


if __name__ == "__main__":
    asyncio.run(main())