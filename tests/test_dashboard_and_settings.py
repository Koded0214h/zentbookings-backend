from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import sample_property

from app.services import paystack


def _dates(days_ahead: int = 3, nights: int = 2) -> tuple[str, str]:
    d1 = date.today() + timedelta(days=days_ahead)
    d2 = d1 + timedelta(days=nights)
    return d1.isoformat(), d2.isoformat()


@pytest.fixture
def fake_paystack_for_dashboard(monkeypatch):
    async def init(*, email, amount_naira, reference, callback_url, metadata=None):
        return {
            "authorization_url": f"https://checkout.paystack.com/{reference}",
            "access_code": "code123",
            "reference": reference,
        }

    monkeypatch.setattr(paystack, "initialize_transaction", init)


async def test_staff_settings_defaults_and_update(client, agent_auth):
    got = await client.get("/api/staff/settings", headers=agent_auth["headers"])
    assert got.status_code == 200
    body = got.json()
    assert body["notifyNewBooking"] is True
    assert body["timezone"] == "Africa/Lagos"
    assert body["payoutBankCode"] is None

    updated = await client.put(
        "/api/staff/settings",
        json={
            "payoutBankCode": "058",
            "payoutBankName": "GTBank",
            "payoutAccountNumber": "0123456789",
            "payoutAccountName": "Ada Agent",
            "notifyNewMessage": False,
        },
        headers=agent_auth["headers"],
    )
    assert updated.status_code == 200
    out = updated.json()
    assert out["payoutBankCode"] == "058"
    assert out["notifyNewMessage"] is False
    assert out["notifyNewBooking"] is True  # untouched field stays


async def test_dashboard_requires_staff(client, registered_user):
    token = registered_user["body"]["token"]
    res = await client.get("/api/agent/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


async def test_dashboard_scoped_to_assigned_properties_for_agent(client, admin_auth, agent_auth):
    pid = (
        await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    ).json()["id"]
    other_pid = (
        await client.post(
            "/api/properties", json=sample_property(title="Not mine"), headers=admin_auth
        )
    ).json()["id"]
    await client.post(
        f"/api/admin/properties/{pid}/agents",
        json={"agentId": agent_auth["id"]},
        headers=admin_auth,
    )

    empty = await client.get("/api/agent/dashboard", headers=agent_auth["headers"])
    assert empty.status_code == 200
    assert empty.json()["totalListings"] == 1  # scoped, not the platform total of 2
    assert empty.json()["activeBookings"] == 0
    assert empty.json()["pendingPayouts"] == 0

    admin_view = await client.get("/api/agent/dashboard", headers=admin_auth)
    assert admin_view.json()["totalListings"] == 2

    del other_pid  # only used to make the platform total 2 vs agent-scoped 1


async def test_dashboard_reflects_wallet_after_settlement(
    client, admin_auth, session_factory, fake_paystack_for_dashboard
):
    pid = (
        await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    ).json()["id"]
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
    reference = created.json()["payment"]["reference"]

    import hashlib
    import hmac
    import json as _json

    from app.core.config import settings

    body = {"event": "charge.success", "data": {"reference": reference, "status": "success"}}
    raw = _json.dumps(body).encode()
    sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw, hashlib.sha512).hexdigest()
    await client.post(
        "/api/payments/webhook/paystack",
        content=raw,
        headers={"content-type": "application/json", "x-paystack-signature": sig},
    )

    dash = await client.get("/api/agent/dashboard", headers=admin_auth)
    assert dash.status_code == 200
    assert dash.json()["activeBookings"] == 1
    assert dash.json()["totalEarnings"] > 0
    assert dash.json()["pendingPayouts"] == dash.json()["totalEarnings"]
    assert len(dash.json()["monthlyRevenue"]) == 1
