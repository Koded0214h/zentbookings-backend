from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, timedelta

import pytest
from conftest import sample_property

from app.core.config import settings
from app.services.payment_providers import bachs

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_bachs(monkeypatch):
    async def init(**kwargs):
        return {
            "authorization_url": f"https://checkout.bachs.io/{kwargs['reference']}",
            "reference": kwargs["reference"],
            "provider_id": "chk_test",
        }

    monkeypatch.setattr(bachs.provider, "initialize_payment", init)

    async def transfer(**kwargs):
        return {"reference": kwargs["reference"], "status": "success"}

    monkeypatch.setattr(bachs.provider, "disburse_to_bank", transfer)


def _dates() -> tuple[str, str]:
    start = date.today() + timedelta(days=5)
    return start.isoformat(), (start + timedelta(days=3)).isoformat()


def _signed_success(reference: str, amount: int) -> tuple[bytes, str]:
    raw = json.dumps(
        {
            "type": "collection.succeeded",
            "data": {
                "reference": reference,
                "status": "SUCCEEDED",
                "amount": f"{amount}.00",
                "currency": "NGN",
            },
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        settings.BACHS_WEBHOOK_SECRET.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return raw, f"t={timestamp},v1={signature}"


async def _settle_assigned_agent_booking(
    client, admin_auth, agent_auth
) -> tuple[int, int, int]:
    prop = await client.post(
        "/api/properties",
        json=sample_property(price=500_000, period="Per Night", category="Shortlet"),
        headers=admin_auth,
    )
    property_id = prop.json()["id"]
    assigned = await client.post(
        f"/api/admin/properties/{property_id}/agents",
        json={"agentId": agent_auth["id"]},
        headers=admin_auth,
    )
    assert assigned.status_code == 201, assigned.text
    check_in, check_out = _dates()
    booking = await client.post(
        "/api/bookings",
        json={
            "propertyId": property_id,
            "guestName": "Paying Guest",
            "guestEmail": "guest@example.com",
            "guestPhone": "+2348000000000",
            "checkIn": check_in,
            "checkOut": check_out,
        },
    )
    assert booking.status_code == 201, booking.text
    body = booking.json()
    raw, signature = _signed_success(
        body["payment"]["reference"], body["booking"]["totalAmount"]
    )
    webhook = await client.post(
        "/api/payments/webhook/bachs",
        content=raw,
        headers={"content-type": "application/json", "x-bachs-signature-v2": signature},
    )
    assert webhook.status_code == 200, webhook.text
    return (
        body["booking"]["totalAmount"],
        body["booking"]["processingFee"],
        property_id,
    )


async def test_70_30_split_and_admin_approved_payout(
    client, admin_auth, agent_auth
):
    total, processing_fee, _ = await _settle_assigned_agent_booking(
        client, admin_auth, agent_auth
    )
    revenue_base = total - processing_fee
    agent_share = round(revenue_base * 70 / 100)

    wallet = await client.get("/api/staff/wallet", headers=agent_auth["headers"])
    assert wallet.json()["balance"] == agent_share

    escrow = await client.get("/api/admin/escrow", headers=admin_auth)
    allocation = escrow.json()[0]
    assert allocation["agentId"] == agent_auth["id"]
    assert allocation["grossAmount"] == total
    assert allocation["processingFee"] == processing_fee
    assert allocation["agentAmount"] == agent_share
    assert allocation["platformAmount"] == total - agent_share

    settings_response = await client.put(
        "/api/staff/settings",
        json={
            "payoutBankCode": "058",
            "payoutBankName": "GTBank",
            "payoutAccountNumber": "0123456789",
            "payoutAccountName": "Ada Agent",
        },
        headers=agent_auth["headers"],
    )
    assert settings_response.status_code == 200
    requested = await client.post(
        "/api/staff/wallet/payouts",
        json={"amount": agent_share},
        headers=agent_auth["headers"],
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["status"] == "PENDING"
    assert (await client.get("/api/staff/wallet", headers=agent_auth["headers"])).json()[
        "balance"
    ] == 0

    payout_id = requested.json()["id"]
    approved = await client.patch(
        f"/api/admin/payouts/{payout_id}",
        json={"decision": "approve"},
        headers=admin_auth,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["transferReference"] == f"zent-{payout_id}"

    raw = json.dumps(
        {
            "type": "payout.paid",
            "data": {"reference": f"zent-{payout_id}", "status": "completed"},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        settings.BACHS_WEBHOOK_SECRET.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    transfer_webhook = await client.post(
        "/api/payments/webhook/bachs",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-bachs-signature-v2": f"t={timestamp},v1={signature}",
        },
    )
    assert transfer_webhook.status_code == 200
    payouts = await client.get("/api/staff/wallet/payouts", headers=agent_auth["headers"])
    assert payouts.json()[0]["status"] == "DISBURSED"


async def test_rejected_payout_returns_reserved_funds(client, admin_auth, agent_auth):
    total, processing_fee, _ = await _settle_assigned_agent_booking(
        client, admin_auth, agent_auth
    )
    amount = round((total - processing_fee) * 70 / 100)
    await client.put(
        "/api/staff/settings",
        json={
            "payoutBankCode": "058",
            "payoutBankName": "GTBank",
            "payoutAccountNumber": "0123456789",
            "payoutAccountName": "Ada Agent",
        },
        headers=agent_auth["headers"],
    )
    requested = await client.post(
        "/api/staff/wallet/payouts", json={"amount": amount}, headers=agent_auth["headers"]
    )
    payout_id = requested.json()["id"]
    rejected = await client.patch(
        f"/api/admin/payouts/{payout_id}",
        json={"decision": "reject", "note": "Bank details need correction"},
        headers=admin_auth,
    )
    assert rejected.status_code == 200
    wallet = await client.get("/api/staff/wallet", headers=agent_auth["headers"])
    assert wallet.json()["balance"] == amount
    assert wallet.json()["transactions"][0]["type"] == "REFUND"
