from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import sample_property
from sqlalchemy import select

from app.models.booking import Payment
from app.services.payment_providers import bachs


@pytest.fixture
def fake_bachs(monkeypatch):
    async def initialize(**kwargs):
        reference = kwargs["reference"]
        return {
            "authorization_url": f"https://checkout.bachs.io/{reference}",
            "reference": reference,
            "provider_id": "chk_admin_test",
        }

    monkeypatch.setattr(bachs.provider, "initialize_payment", initialize)


async def _pending_booking(client, admin_auth, fake_bachs) -> dict:
    prop = await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    check_in = date.today() + timedelta(days=20)
    response = await client.post(
        "/api/bookings",
        json={
            "propertyId": prop.json()["id"],
            "guestName": "Admin Test",
            "guestEmail": "finance@example.com",
            "guestPhone": "+2348000000000",
            "checkIn": check_in.isoformat(),
            "checkOut": (check_in + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_admin_dashboard_config_and_exports(client, admin_auth):
    dashboard = await client.get("/api/admin/dashboard", headers=admin_auth)
    assert dashboard.status_code == 200
    assert dashboard.json()["grossCollections"] == 0
    assert dashboard.json()["platformRevenue"] == 0

    config = await client.get("/api/admin/config", headers=admin_auth)
    assert config.status_code == 200
    assert config.json()["paymentProvider"] == "bachs"
    assert config.json()["processingFeePercent"] == 2
    assert "bachsConfigured" in config.json()

    for endpoint, key in (
        ("wallets", "wallets"),
        ("escrow", "allocations"),
        ("payouts", "payouts"),
    ):
        response = await client.get(f"/api/admin/finance/{endpoint}", headers=admin_auth)
        assert response.status_code == 200
        assert response.json()[key] == []
        assert response.json()["total"] == 0

    report = await client.get("/api/admin/reports/payments.csv", headers=admin_auth)
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/csv")
    assert report.text.startswith("id,reference,booking_id")


async def test_admin_payment_ledger_detail_and_adjustment(
    client, admin_auth, fake_bachs, session_factory
):
    created = await _pending_booking(client, admin_auth, fake_bachs)
    reference = created["payment"]["reference"]

    ledger = await client.get(
        "/api/admin/payments", params={"q": "finance@example.com"}, headers=admin_auth
    )
    assert ledger.status_code == 200
    assert ledger.json()["total"] == 1
    payment_id = ledger.json()["payments"][0]["id"]
    assert ledger.json()["payments"][0]["reference"] == reference

    detail = await client.get(f"/api/admin/payments/{payment_id}", headers=admin_auth)
    assert detail.status_code == 200
    assert detail.json()["adjustments"] == []

    rejected = await client.post(
        f"/api/admin/payments/{payment_id}/adjustments",
        json={"type": "REFUND", "amount": 100, "reason": "Guest request"},
        headers=admin_auth,
    )
    assert rejected.status_code == 409

    async with session_factory() as db:
        payment = await db.scalar(select(Payment).where(Payment.id == payment_id))
        payment.status = "SUCCESS"
        await db.commit()

    adjustment = await client.post(
        f"/api/admin/payments/{payment_id}/adjustments",
        json={
            "type": "REFUND",
            "amount": 100,
            "reason": "Guest request",
            "status": "COMPLETED",
            "providerReference": "provider-ref-1",
        },
        headers=admin_auth,
    )
    assert adjustment.status_code == 201, adjustment.text
    assert adjustment.json()["status"] == "COMPLETED"

    dashboard = await client.get("/api/admin/dashboard", headers=admin_auth)
    assert dashboard.json()["refundedAmount"] == 100


async def test_admin_booking_state_control(client, admin_auth, fake_bachs):
    created = await _pending_booking(client, admin_auth, fake_bachs)
    booking_id = created["booking"]["id"]

    invalid = await client.patch(
        f"/api/admin/bookings/{booking_id}",
        json={"status": "COMPLETED"},
        headers=admin_auth,
    )
    assert invalid.status_code == 409

    cancelled = await client.patch(
        f"/api/admin/bookings/{booking_id}",
        json={"status": "CANCELLED", "notes": "Cancelled by operations"},
        headers=admin_auth,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["notes"] == "Cancelled by operations"
