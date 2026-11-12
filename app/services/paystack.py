from __future__ import annotations

import hashlib
import hmac

import httpx

from app.core.config import settings
from app.core.exceptions import AppError

BASE_URL = "https://api.paystack.co"


class PaystackNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(503, "paystack_not_configured", "Payments are not configured.")


class PaystackError(AppError):
    def __init__(self, message: str = "Payment provider error.") -> None:
        super().__init__(502, "paystack_error", message)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}


async def initialize_transaction(
    *,
    email: str,
    amount_naira: int,
    reference: str,
    callback_url: str,
    metadata: dict | None = None,
) -> dict:
    """amount_naira is whole Naira; Paystack wants kobo (x100)."""
    if not settings.paystack_configured:
        raise PaystackNotConfigured()
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{BASE_URL}/transaction/initialize",
            headers=_headers(),
            json={
                "email": email,
                "amount": amount_naira * 100,
                "reference": reference,
                "callback_url": callback_url,
                "currency": "NGN",
                "metadata": metadata or {},
            },
        )
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code >= 400 or not body.get("status"):
        raise PaystackError(body.get("message") or f"initialize failed ({res.status_code})")
    data = body["data"]
    return {
        "authorization_url": data["authorization_url"],
        "access_code": data["access_code"],
        "reference": data["reference"],
    }


async def verify_transaction(reference: str) -> dict:
    if not settings.paystack_configured:
        raise PaystackNotConfigured()
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{BASE_URL}/transaction/verify/{reference}", headers=_headers())
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code >= 400 or not body.get("status"):
        raise PaystackError(body.get("message") or f"verify failed ({res.status_code})")
    return body["data"]


async def disburse_to_bank(
    *,
    amount_naira: int,
    account_name: str,
    account_number: str,
    bank_code: str,
    reference: str,
    reason: str,
) -> dict:
    """Create a Paystack transfer recipient and send funds from the platform balance."""
    if not settings.paystack_configured:
        raise PaystackNotConfigured()
    async with httpx.AsyncClient(timeout=20) as client:
        recipient_res = await client.post(
            f"{BASE_URL}/transferrecipient",
            headers=_headers(),
            json={
                "type": "nuban",
                "name": account_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": "NGN",
            },
        )
        recipient_body = (
            recipient_res.json()
            if recipient_res.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if recipient_res.status_code >= 400 or not recipient_body.get("status"):
            raise PaystackError(
                recipient_body.get("message")
                or f"recipient creation failed ({recipient_res.status_code})"
            )
        recipient_code = recipient_body["data"]["recipient_code"]
        transfer_res = await client.post(
            f"{BASE_URL}/transfer",
            headers=_headers(),
            json={
                "source": "balance",
                "amount": amount_naira * 100,
                "recipient": recipient_code,
                "reference": reference,
                "reason": reason,
                "currency": "NGN",
            },
        )
        transfer_body = (
            transfer_res.json()
            if transfer_res.headers.get("content-type", "").startswith("application/json")
            else {}
        )
    if transfer_res.status_code >= 400 or not transfer_body.get("status"):
        raise PaystackError(
            transfer_body.get("message") or f"transfer failed ({transfer_res.status_code})"
        )
    return transfer_body["data"]


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed, signature)
