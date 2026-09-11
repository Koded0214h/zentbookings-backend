from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import _register, sample_property

from app.services import paystack


def _dates(days_ahead: int = 3, nights: int = 2) -> tuple[str, str]:
    d1 = date.today() + timedelta(days=days_ahead)
    d2 = d1 + timedelta(days=nights)
    return d1.isoformat(), d2.isoformat()


def _body(pid: int, **over) -> dict:
    check_in, check_out = _dates()
    body = {
        "propertyId": pid,
        "guestName": "Guest Visitor",
        "guestEmail": "guest@example.com",
        "guestPhone": "+2348010000000",
        "checkIn": check_in,
        "checkOut": check_out,
    }
    body.update(over)
    return body


@pytest.fixture
def fake_paystack(monkeypatch):
    calls: dict[str, list] = {"init": []}

    async def init(*, email, amount_naira, reference, callback_url, metadata=None):
        calls["init"].append({"email": email, "amount": amount_naira, "reference": reference})
        return {
            "authorization_url": f"https://checkout.paystack.com/{reference}",
            "access_code": "code123",
            "reference": reference,
        }

    monkeypatch.setattr(paystack, "initialize_transaction", init)
    return calls


async def test_create_booking_success(client, booking_property, fake_paystack):
    res = await client.post("/api/bookings", json=_body(booking_property))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["booking"]["status"] == "PENDING_PAYMENT"
    assert body["booking"]["nights"] == 2
    assert body["booking"]["subtotal"] == 850000 * 2
    assert body["booking"]["totalAmount"] == 850000 * 2  # no cleaning/deposit by default
    assert body["payment"]["authorizationUrl"].startswith("https://checkout.paystack.com/")
    assert fake_paystack["init"][0]["amount"] == 850000 * 2


async def test_create_booking_checkout_before_checkin_is_422(
    client, booking_property, fake_paystack
):
    check_in, _ = _dates()
    res = await client.post(
        "/api/bookings", json=_body(booking_property, checkIn=check_in, checkOut=check_in)
    )
    assert res.status_code == 422


async def test_create_booking_past_checkin_is_409(client, booking_property, fake_paystack):
    res = await client.post(
        "/api/bookings", json=_body(booking_property, checkIn="2020-01-01", checkOut="2020-01-03")
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "dates_unavailable"


async def test_minimum_stay_enforced(client, admin_auth, fake_paystack):
    pid = (
        await client.post(
            "/api/properties",
            json=sample_property(minimumStayNights=5),
            headers=admin_auth,
        )
    ).json()["id"]
    res = await client.post("/api/bookings", json=_body(pid))  # only 2 nights
    assert res.status_code == 409


async def test_max_guests_enforced(client, admin_auth, fake_paystack):
    pid = (
        await client.post("/api/properties", json=sample_property(maxGuests=2), headers=admin_auth)
    ).json()["id"]
    res = await client.post("/api/bookings", json=_body(pid, guests=3))
    assert res.status_code == 422


async def test_guest_missing_fields_is_422(client, booking_property, fake_paystack):
    res = await client.post(
        "/api/bookings",
        json={
            "propertyId": booking_property,
            "checkIn": _dates()[0],
            "checkOut": _dates()[1],
        },
    )
    assert res.status_code == 422


async def test_unknown_property_is_404(client, fake_paystack):
    res = await client.post("/api/bookings", json=_body(999999))
    assert res.status_code == 404


async def test_overlap_rejected_only_for_confirmed_bookings(
    client, booking_property, fake_paystack, session_factory
):
    check_in, check_out = _dates(days_ahead=10)
    # first booking stays PENDING_PAYMENT -> does not block
    await client.post(
        "/api/bookings", json=_body(booking_property, checkIn=check_in, checkOut=check_out)
    )
    still_open = await client.post(
        "/api/bookings",
        json=_body(
            booking_property, checkIn=check_in, checkOut=check_out, guestEmail="two@example.com"
        ),
    )
    assert still_open.status_code == 201

    # confirm one of them directly, then a new overlapping booking must fail
    from sqlalchemy import select

    from app.models.booking import Booking

    async with session_factory() as db:
        b = (
            (await db.execute(select(Booking).where(Booking.property_id == booking_property)))
            .scalars()
            .first()
        )
        b.status = "CONFIRMED"
        await db.commit()

    blocked = await client.post(
        "/api/bookings",
        json=_body(
            booking_property, checkIn=check_in, checkOut=check_out, guestEmail="three@example.com"
        ),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "dates_unavailable"


async def test_guest_lookup_and_cancel(client, booking_property, fake_paystack, email_sender):
    made = await client.post("/api/bookings", json=_body(booking_property))
    code = made.json()["booking"]["confirmationCode"]

    good = await client.post(
        "/api/bookings/lookup", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    assert good.status_code == 200

    wrong = await client.post(
        "/api/bookings/lookup", json={"confirmationCode": code, "email": "wrong@example.com"}
    )
    assert wrong.status_code == 404

    cancelled = await client.post(
        "/api/bookings/cancel", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert "cancelled" in email_sender.sent[-1]["subject"].lower()


async def test_list_is_self_scoped_but_staff_sees_all(
    client, booking_property, registered_user, admin_auth, fake_paystack
):
    token = registered_user["body"]["token"]
    await client.post(
        "/api/bookings",
        json=_body(booking_property),
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post("/api/bookings", json=_body(booking_property, guestEmail="g2@example.com"))

    mine = await client.get("/api/bookings", headers={"Authorization": f"Bearer {token}"})
    assert mine.json()["total"] == 1

    staff_view = await client.get("/api/bookings", headers=admin_auth)
    assert staff_view.json()["total"] == 2


async def test_detail_ownership(
    client, booking_property, registered_user, admin_auth, fake_paystack, email_sender
):
    token = registered_user["body"]["token"]
    made = await client.post(
        "/api/bookings",
        json=_body(booking_property),
        headers={"Authorization": f"Bearer {token}"},
    )
    bid = made.json()["booking"]["id"]

    owner = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"/api/bookings/{bid}", headers=owner)).status_code == 200
    assert (await client.get(f"/api/bookings/{bid}", headers=admin_auth)).status_code == 200

    stranger = await _register(client, email_sender, "no@example.com", "N", "O")
    other_auth = {"Authorization": f"Bearer {stranger['token']}"}
    assert (await client.get(f"/api/bookings/{bid}", headers=other_auth)).status_code == 403


async def test_blocked_dates_reflects_confirmed_bookings(
    client, booking_property, fake_paystack, session_factory
):
    check_in, check_out = _dates(days_ahead=20)
    made = await client.post(
        "/api/bookings", json=_body(booking_property, checkIn=check_in, checkOut=check_out)
    )
    bid = made.json()["booking"]["id"]

    empty = await client.get(f"/api/properties/{booking_property}/blocked-dates")
    assert empty.json()["ranges"] == []  # still PENDING_PAYMENT

    from app.models.booking import Booking

    async with session_factory() as db:
        b = await db.get(Booking, bid)
        b.status = "CONFIRMED"
        await db.commit()

    now_blocked = await client.get(f"/api/properties/{booking_property}/blocked-dates")
    ranges = now_blocked.json()["ranges"]
    assert len(ranges) == 1
    assert ranges[0]["checkIn"] == check_in
    assert ranges[0]["checkOut"] == check_out


async def test_expire_unpaid_bookings(client, booking_property, fake_paystack, session_factory):
    from datetime import UTC, datetime
    from datetime import timedelta as td

    from sqlalchemy import select

    from app.models.booking import Booking
    from app.services.booking_service import expire_unpaid

    await client.post("/api/bookings", json=_body(booking_property))

    async with session_factory() as db:
        b = (await db.execute(select(Booking))).scalars().first()
        b.created_at = datetime.now(UTC) - td(minutes=60)
        await db.commit()

    async with session_factory() as db:
        count = await expire_unpaid(db, older_than_minutes=30)
        await db.commit()
    assert count == 1
