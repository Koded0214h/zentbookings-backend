from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.payment_providers.base import ProviderEvent


class BachsNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(503, "bachs_not_configured", "Bachs payments are not configured.")


class BachsError(AppError):
    def __init__(self, message: str = "Bachs payment provider error.") -> None:
        super().__init__(502, "bachs_error", message)


class BachsDestinationPending(AppError):
    def __init__(self) -> None:
        super().__init__(
            409,
            "bachs_destination_pending",
            "The agent bank destination is awaiting approval in Bachs. Approve it and retry.",
        )


class BachsProvider:
    name = "bachs"

    @property
    def base_url(self) -> str:
        if settings.BACHS_BASE_URL:
            return settings.BACHS_BASE_URL.rstrip("/")
        key = settings.BACHS_API_KEY or ""
        return "https://api.bachs.io" if key.startswith("sk_live_") else "https://sandbox-api.bachs.io"

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        if not settings.bachs_configured:
            raise BachsNotConfigured()
        headers = {
            "Authorization": f"Bearer {settings.BACHS_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _body(res: httpx.Response) -> dict:
        if res.headers.get("content-type", "").startswith("application/json"):
            value = res.json()
            return value if isinstance(value, dict) else {}
        return {}

    @classmethod
    def _require_success(cls, res: httpx.Response, operation: str) -> dict:
        body = cls._body(res)
        if res.status_code >= 400:
            raise BachsError(body.get("detail") or f"{operation} failed ({res.status_code})")
        return body

    async def initialize_payment(
        self,
        *,
        email: str,
        name: str,
        phone: str,
        amount_naira: int,
        reference: str,
        callback_url: str,
        metadata: dict | None = None,
    ) -> dict:
        payload = {
            "pricing": {"currency": "NGN", "amount": f"{amount_naira:.2f}"},
            "customer": {"email": email, "name": name, "phone_number": phone},
            "success_url": callback_url,
            "cancel_url": callback_url,
            "reference": reference,
            "metadata": metadata or {},
            "payment_method_types": ["NGN_CARD", "NGN_BANK_TRANSFER"],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                f"{self.base_url}/v1/checkout-sessions",
                headers=self._headers(idempotency_key=f"checkout-{reference}"),
                json=payload,
            )
        data = self._require_success(res, "checkout initialization")
        return {
            "authorization_url": data["checkout_url"],
            "reference": data.get("reference") or reference,
            "provider_id": data["checkout_id"],
        }

    async def verify_payment(self, provider_id: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{self.base_url}/v1/checkout-sessions/{provider_id}",
                headers=self._headers(),
            )
        return self._require_success(res, "checkout verification")

    def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        secret = settings.BACHS_WEBHOOK_SECRET
        if not secret:
            raise BachsNotConfigured()
        signature_v2 = headers.get("x-bachs-signature-v2")
        timestamp_text = headers.get("x-bachs-timestamp")
        signatures: list[str] = []
        if signature_v2:
            parts = [part.split("=", 1) for part in signature_v2.split(",") if "=" in part]
            timestamp_text = next((value for key, value in parts if key == "t"), timestamp_text)
            signatures = [value for key, value in parts if key == "v1"]
        elif headers.get("x-bachs-signature"):
            signatures = [headers["x-bachs-signature"]]
        try:
            timestamp = int(timestamp_text or "")
        except ValueError:
            timestamp = 0
        if not timestamp or abs(int(time.time()) - timestamp) > 300:
            raise AppError(401, "invalid_signature", "Invalid or stale Bachs webhook signature.")
        expected = hmac.new(
            secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, value) for value in signatures):
            raise AppError(401, "invalid_signature", "Invalid Bachs webhook signature.")
        try:
            event = json.loads(raw_body)
        except ValueError:
            raise AppError(400, "invalid_payload", "Malformed webhook payload.") from None
        data = event.get("data") or {}
        event_type = event.get("type")
        kinds = {
            "collection.succeeded": "payment_success",
            "collection.failed": "payment_failed",
            "payout.paid": "payout_success",
            "payout.failed": "payout_failed",
        }
        return ProviderEvent(
            kind=kinds.get(event_type, "ignored"),
            reference=data.get("reference"),
            data=data,
        )

    async def _find_destination(
        self, client: httpx.AsyncClient, *, account_number: str, bank_code: str
    ) -> dict | None:
        res = await client.get(
            f"{self.base_url}/v1/payouts/destinations", headers=self._headers()
        )
        body = self._require_success(res, "destination lookup")
        rows = body.get("data", body.get("items", []))
        if not isinstance(rows, list):
            return None
        return next(
            (
                row
                for row in rows
                if row.get("account_number") == account_number and row.get("bank_code") == bank_code
            ),
            None,
        )

    async def disburse_to_bank(
        self,
        *,
        amount_naira: int,
        account_name: str,
        account_number: str,
        bank_code: str,
        reference: str,
        reason: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            destination = await self._find_destination(
                client, account_number=account_number, bank_code=bank_code
            )
            if destination is None:
                res = await client.post(
                    f"{self.base_url}/v1/payouts/destinations",
                    headers=self._headers(idempotency_key=f"destination-{bank_code}-{account_number}"),
                    json={
                        "name": account_name,
                        "type": "bank_account",
                        "currency": "NGN",
                        "account_number": account_number,
                        "bank_code": bank_code,
                    },
                )
                destination = self._require_success(res, "destination creation")
            if not destination.get("is_usable"):
                raise BachsDestinationPending()
            res = await client.post(
                f"{self.base_url}/v1/payouts",
                headers=self._headers(idempotency_key=f"payout-{reference}"),
                json={
                    "destination": destination["id"],
                    "amount": f"{amount_naira:.2f}",
                    "reference": reference,
                    "narration": reason[:100],
                },
            )
        payout = self._require_success(res, "payout creation")
        return {
            "reference": payout.get("reference") or reference,
            "provider_id": payout.get("id"),
            "status": payout.get("status"),
        }


provider = BachsProvider()
