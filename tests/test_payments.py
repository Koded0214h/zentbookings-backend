from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, timedelta

import pytest
from conftest import sample_property

from app.core.config import settings
from app.services import paystack


def _dates(days_ahead: int = 3, nights: int = 2) -> tuple[str, str]:
    d1 = date.today() + timedelta(days=days_ahead)
    d2 = d1 + timedelta(days=nights)
    return d1.isoformat(), d2.isoformat()


def _sign(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw, hashlib.sha512).hexdigest()
    return raw, sig


@pytest.fixture
def fake_paystack(monkeypatch):
    async def init(*, email, amount_naira, reference, callback_url, metadata=None):
        return {
            "authorization_url": f"https://checkout.paystack.com/{reference}",
            "access_code": "code123",
            "reference": reference,
        }

    monkeypatch.setattr(paystack, "initialize_transaction", init)


async def test_payment_config_exposes_public_key(client):
    res = await client.get("/api/payments/config")
    assert res.status_code == 200
    assert res.json()["publicKey"] == settings.PAYSTACK_PUBLIC_KEY


async def test_webhook_rejects_bad_signature(client):
    body = {"event": "charge.success", "data": {"reference": "does-not-matter"}}
    res = await client.post(
        "/api/payments/webhook/paystack",
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-paystack-signature": "bogus"},
    )
    assert res.status_code == 401


async def test_webhook_unknown_reference_is_noop(client):
    raw, sig = _sign({"event": "charge.success", "data": {"reference": "not-a-real-one"}})
    res = await client.post(
        "/api/payments/webhook/paystack",
        content=raw,
        headers={"content-type": "application/json", "x-paystack-signature": sig},
    )
    assert res.status_code == 200
    assert res.json() == {"received": True}


async def test_webhook_charge_success_confirms_booking_and_credits_wallet(
    client, admin_auth, fake_paystack, session_factory
):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    check_in, check_out = _dates()
    created = await client.post(
        "/api/bookings",
        json={
            "propertyId": pid,
            "guestName": "G",
            "guestEmail": "g@example.com",
            "guestPhone": "+2348000000000",
            "checkIn": check_in,
            "checkOut": check_out,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    reference = body["payment"]["reference"]
    booking_id = body["booking"]["id"]
    total = body["booking"]["totalAmount"]

    raw, sig = _sign(
        {"event": "charge.success", "data": {"reference": reference, "status": "success"}}
    )
    res = await client.post(
        "/api/payments/webhook/paystack",
        content=raw,
        headers={"content-type": "application/json", "x-paystack-signature": sig},
    )
    assert res.status_code == 200

    confirmed = await client.get(f"/api/bookings/{booking_id}", headers=admin_auth)
    assert confirmed.json()["status"] == "CONFIRMED"

    wallet = await client.get("/api/staff/wallet", headers=admin_auth)
    expected_net = total - round(total * settings.PLATFORM_FEE_PERCENT / 100)
    assert wallet.json()["balance"] == expected_net
    assert wallet.json()["transactions"][0]["type"] == "CREDIT"


async def test_webhook_is_idempotent(client, admin_auth, fake_paystack):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    check_in, check_out = _dates(days_ahead=6)
    created = await client.post(
        "/api/bookings",
        json={
            "propertyId": pid,
            "guestName": "G",
            "guestEmail": "g2@example.com",
            "guestPhone": "+2348000000000",
            "checkIn": check_in,
            "checkOut": check_out,
        },
    )
    reference = created.json()["payment"]["reference"]
    event = {"event": "charge.success", "data": {"reference": reference, "status": "success"}}

    for _ in range(2):
        raw, sig = _sign(event)
        res = await client.post(
            "/api/payments/webhook/paystack",
            content=raw,
            headers={"content-type": "application/json", "x-paystack-signature": sig},
        )
        assert res.status_code == 200

    wallet = await client.get("/api/staff/wallet", headers=admin_auth)
    assert len(wallet.json()["transactions"]) == 1  # only credited once


async def test_webhook_charge_failed_marks_payment_failed(client, admin_auth, fake_paystack):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    check_in, check_out = _dates(days_ahead=9)
    created = await client.post(
        "/api/bookings",
        json={
            "propertyId": pid,
            "guestName": "G",
            "guestEmail": "g3@example.com",
            "guestPhone": "+2348000000000",
            "checkIn": check_in,
            "checkOut": check_out,
        },
    )
    booking_id = created.json()["booking"]["id"]
    reference = created.json()["payment"]["reference"]

    raw, sig = _sign({"event": "charge.failed", "data": {"reference": reference}})
    res = await client.post(
        "/api/payments/webhook/paystack",
        content=raw,
        headers={"content-type": "application/json", "x-paystack-signature": sig},
    )
    assert res.status_code == 200

    still_pending = await client.get(f"/api/bookings/{booking_id}", headers=admin_auth)
    assert still_pending.json()["status"] == "PENDING_PAYMENT"
