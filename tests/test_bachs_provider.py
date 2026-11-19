from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.payment_providers.bachs import BachsDestinationPending, provider

pytestmark = pytest.mark.asyncio


async def test_initialize_checkout_uses_ngn_decimal_and_idempotency(monkeypatch):
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "checkout_id": "chk_test",
                "checkout_url": "https://checkout.bachs.io/c/test",
                "reference": "booking-ref",
            },
        )

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.payment_providers.bachs.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    result = await provider.initialize_payment(
        email="guest@example.com",
        name="Guest",
        phone="+2348000000000",
        amount_naira=500_000,
        reference="booking-ref",
        callback_url="https://zentbookings.com/booking/complete",
        metadata={"booking_id": "bkg_test"},
    )
    assert seen["url"].endswith("/v1/checkout-sessions")
    assert seen["headers"]["idempotency-key"] == "checkout-booking-ref"
    assert seen["json"]["pricing"] == {"currency": "NGN", "amount": "500000.00"}
    assert result["provider_id"] == "chk_test"


async def test_webhook_rejects_stale_timestamp():
    raw = b'{"type":"collection.succeeded","data":{}}'
    timestamp = int(time.time()) - 301
    signature = hmac.new(
        settings.BACHS_WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    with pytest.raises(AppError) as caught:
        provider.parse_webhook(
            raw, {"x-bachs-signature-v2": f"t={timestamp},v1={signature}"}
        )
    assert caught.value.status_code == 401


async def test_payout_waits_for_destination_approval(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "pd_pending",
                        "account_number": "0123456789",
                        "bank_code": "058",
                        "is_usable": False,
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.payment_providers.bachs.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    with pytest.raises(BachsDestinationPending):
        await provider.disburse_to_bank(
            amount_naira=10_000,
            account_name="Ada Agent",
            account_number="0123456789",
            bank_code="058",
            reference="zent-payout-test",
            reason="Zent payout",
        )
