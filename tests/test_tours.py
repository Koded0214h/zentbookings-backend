from __future__ import annotations

from conftest import _register, next_open_slot


def _booking(property_id: int, **over) -> dict:
    d, t = next_open_slot()
    body = {
        "propertyId": property_id,
        "visitorName": "Guest Visitor",
        "visitorEmail": "guest@example.com",
        "visitorPhone": "+2348012345678",
        "scheduledDate": d,
        "scheduledTime": t,
        "notes": "Interested in a long lease",
    }
    body.update(over)
    return body


async def test_guest_can_book_without_auth(client, booking_property, email_sender):
    res = await client.post("/api/tours", json=_booking(booking_property))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "CONFIRMED"  # default schedule auto-confirms
    assert body["confirmationCode"].startswith("ZENT-")
    assert body["scheduledAt"].endswith("Z")
    assert body["propertyId"] == booking_property
    assert email_sender.sent[-1]["to"] == "guest@example.com"
    assert "confirmed" in email_sender.sent[-1]["subject"].lower()


async def test_authed_booking_links_user_and_prefills(client, booking_property, registered_user):
    token = registered_user["body"]["token"]
    d, t = next_open_slot(days_ahead=4)
    res = await client.post(
        "/api/tours",
        json={
            "propertyId": booking_property,
            "visitorPhone": "+2348099999999",
            "scheduledDate": d,
            "scheduledTime": t,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    tour_id = res.json()["id"]

    listed = await client.get("/api/tours", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    mine = listed.json()["tours"]
    assert len(mine) == 1
    assert mine[0]["id"] == tour_id
    assert mine[0]["visitorEmail"] == "amara@example.com"  # from profile
    assert mine[0]["visitorName"] == "Amara Adeyemi"


async def test_guest_missing_fields_is_422(client, booking_property):
    res = await client.post(
        "/api/tours",
        json={
            "propertyId": booking_property,
            "scheduledDate": next_open_slot()[0],
            "scheduledTime": "10:00",
        },
    )
    assert res.status_code == 422


async def test_reject_non_slot_time(client, booking_property):
    res = await client.post(
        "/api/tours", json=_booking(booking_property, scheduledTime="10:30")
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "slot_unavailable"


async def test_reject_closed_sunday(client, booking_property):
    from datetime import date, timedelta

    d = date.today() + timedelta(days=3)
    while d.weekday() != 6:
        d += timedelta(days=1)
    res = await client.post(
        "/api/tours", json=_booking(booking_property, scheduledDate=d.isoformat())
    )
    assert res.status_code == 409


async def test_reject_past_date(client, booking_property):
    res = await client.post(
        "/api/tours", json=_booking(booking_property, scheduledDate="2020-01-06")
    )
    assert res.status_code == 409


async def test_capacity_is_enforced(client, booking_property, admin_auth):
    # capacity defaults to 1
    d, t = next_open_slot(days_ahead=5)
    first = await client.post(
        "/api/tours", json=_booking(booking_property, scheduledDate=d, scheduledTime=t)
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/tours",
        json=_booking(
            booking_property, scheduledDate=d, scheduledTime=t, visitorEmail="other@example.com"
        ),
    )
    assert second.status_code == 409
    assert "fully booked" in second.json()["error"]["message"].lower()

    # cancelling the first frees the slot
    code = first.json()["confirmationCode"]
    await client.post(
        "/api/tours/cancel", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    third = await client.post(
        "/api/tours",
        json=_booking(
            booking_property, scheduledDate=d, scheduledTime=t, visitorEmail="third@example.com"
        ),
    )
    assert third.status_code == 201


async def test_list_requires_auth(client):
    assert (await client.get("/api/tours")).status_code in (401, 403)


async def test_list_is_self_scoped_but_staff_sees_all(
    client, booking_property, registered_user, admin_auth
):
    token = registered_user["body"]["token"]
    d, _ = next_open_slot(days_ahead=6)
    await client.post(
        "/api/tours",
        json=_booking(booking_property, scheduledDate=d, scheduledTime="10:00"),
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/api/tours",
        json=_booking(
            booking_property, scheduledDate=d, scheduledTime="14:00", visitorEmail="g2@example.com"
        ),
    )

    auth = {"Authorization": f"Bearer {token}"}
    user_view = (await client.get("/api/tours", headers=auth)).json()
    assert user_view["total"] == 1

    staff_view = (await client.get("/api/tours", headers=admin_auth)).json()
    assert staff_view["total"] == 2

    filtered = (
        await client.get(
            "/api/tours", params={"propertyId": booking_property, "status": "confirmed"},
            headers=admin_auth,
        )
    ).json()
    assert filtered["total"] == 2


async def test_detail_ownership(
    client, booking_property, registered_user, admin_auth, email_sender
):
    token = registered_user["body"]["token"]
    made = await client.post(
        "/api/tours",
        json=_booking(booking_property),
        headers={"Authorization": f"Bearer {token}"},
    )
    tid = made.json()["id"]

    other = await _register(client, email_sender, "no@example.com", "N", "O")
    owner = {"Authorization": f"Bearer {token}"}
    stranger = {"Authorization": f"Bearer {other['token']}"}

    assert (await client.get(f"/api/tours/{tid}", headers=owner)).status_code == 200
    assert (await client.get(f"/api/tours/{tid}", headers=stranger)).status_code == 403
    assert (await client.get(f"/api/tours/{tid}", headers=admin_auth)).status_code == 200


async def test_guest_lookup_and_cancel(client, booking_property, email_sender):
    made = await client.post("/api/tours", json=_booking(booking_property))
    code = made.json()["confirmationCode"]

    good = await client.post(
        "/api/tours/lookup", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    assert good.status_code == 200
    assert good.json()["confirmationCode"] == code

    bad = await client.post(
        "/api/tours/lookup", json={"confirmationCode": code, "email": "wrong@example.com"}
    )
    assert bad.status_code == 404

    cancelled = await client.post(
        "/api/tours/cancel", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert "cancelled" in email_sender.sent[-1]["subject"].lower()


async def test_confirm_is_staff_only(client, booking_property, registered_user, admin_auth):
    # switch the property to manual confirmation
    await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"autoConfirm": False},
        headers=admin_auth,
    )
    made = await client.post("/api/tours", json=_booking(booking_property))
    assert made.json()["status"] == "PENDING"
    tid = made.json()["id"]

    token = registered_user["body"]["token"]
    denied = await client.post(
        f"/api/tours/{tid}/confirm", headers={"Authorization": f"Bearer {token}"}
    )
    assert denied.status_code == 403

    ok = await client.post(f"/api/tours/{tid}/confirm", headers=admin_auth)
    assert ok.status_code == 200
    assert ok.json()["status"] == "CONFIRMED"
