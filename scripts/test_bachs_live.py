"""Create a real Bachs checkout session using an explicitly supplied live key.

This script creates a hosted checkout URL. Money only moves after a person opens
that URL and completes payment. Secrets are read from the environment and never
printed or written to disk.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a guarded live Bachs checkout")
    parser.add_argument("--amount", type=int, required=True, help="Whole NGN amount (minimum 1000)")
    parser.add_argument("--email", required=True, help="Payer email")
    parser.add_argument("--name", required=True, help="Payer name")
    parser.add_argument("--phone", required=True, help="Payer phone number")
    parser.add_argument("--return-url", required=True, help="Public HTTPS return URL")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required acknowledgement that completing checkout will move real money",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get("BACHS_API_KEY", "")
    if not args.confirm_live:
        raise SystemExit("Refusing: pass --confirm-live after reviewing the amount.")
    if not api_key.startswith("sk_live_"):
        raise SystemExit("Refusing: BACHS_API_KEY must be a live key beginning with sk_live_.")
    if args.amount < 1000:
        raise SystemExit("Refusing: live test amount must be at least NGN 1,000.")
    if not args.return_url.startswith("https://"):
        raise SystemExit("Refusing: --return-url must be public HTTPS.")

    reference = f"zent-live-test-{secrets.token_hex(6)}"
    payload = {
        "pricing": {"currency": "NGN", "amount": f"{args.amount:.2f}"},
        "customer": {
            "email": args.email,
            "name": args.name,
            "phone_number": args.phone,
        },
        "success_url": args.return_url,
        "cancel_url": args.return_url,
        "reference": reference,
        "metadata": {"purpose": "zent_live_key_test"},
        "payment_method_types": ["NGN_CARD", "NGN_BANK_TRANSFER"],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Idempotency-Key": f"checkout-{reference}",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.bachs.io/v1/checkout-sessions", headers=headers, json=payload
        )
    body = (
        response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if response.status_code >= 400:
        detail = body.get("detail", "unknown error")
        raise SystemExit(f"Bachs rejected checkout ({response.status_code}): {detail}")
    print(f"Reference: {body.get('reference', reference)}")
    print(f"Checkout ID: {body['checkout_id']}")
    print(f"Checkout URL: {body['checkout_url']}")
    print("No money has moved yet. Complete the hosted checkout to perform the live test.")


if __name__ == "__main__":
    asyncio.run(main())
