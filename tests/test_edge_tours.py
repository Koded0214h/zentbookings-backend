from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import next_open_slot

from app.core import ratelimit


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "RATE_LIMIT_ENABLED", False)


def _body(pid: int, **over) -> dict:
    d, t = next_open_slot()
    b = {
        "propertyId": pid,
        "visitorName": "Guest",
        "visitorEmail": "guest@example.com",
        "visitorPhone": "+2348010000000",
        "scheduledDate": d,
        "scheduledTime": t,
    }
    b.update(over)
    return b


# ---------------- time / date validation ----------------
async def test_malformed_scheduled_time_is_422(client, booking_property):
    for bad in ("25:00", "23:60", "9:05", "0900", "noon", "12:5"):
        res = await client.post("/api/tours", json=_body(booking_property, scheduledTime=bad))
        assert res.status_code == 422, bad


async def test_non_slot_time_is_409(client, booking_property):
    res = await client.post("/api/tours", json=_body(booking_property, scheduledTime="10:30"))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "slot_unavailable"


async def test_time_at_end_of_window_is_not_a_slot(client, booking_property):
    # default Mon-Fri 10:00-17:00, 60-min slots -> last slot starts 16:00, 17:00 doesn't fit
    res = await client.post("/api/tours", json=_body(booking_property, scheduledTime="17:00"))
    assert res.status_code == 409


async def test_past_date_and_far_future_date_rejected(client, booking_property):
    past = await client.post("/api/tours", json=_body(booking_property, scheduledDate="2020-01-06"))
    assert past.status_code == 409

    far = (date.today() + timedelta(days=365)).isoformat()
    res = await client.post("/api/tours", json=_body(booking_property, scheduledDate=far))
    assert res.status_code == 409


async def test_inside_min_notice_window_rejected(client, booking_property):
    # today, even at a valid slot time, is inside the 12h notice window
    d, _ = next_open_slot(days_ahead=0)
    if d != date.today().isoformat():
        return  # today was a weekend; skip
    res = await client.post(
        "/api/tours", json=_body(booking_property, scheduledDate=d, scheduledTime="10:00")
    )
    assert res.status_code == 409


async def test_unknown_property_is_404(client):
    res = await client.post("/api/tours", json=_body(999999))
    assert res.status_code == 404


async def test_guest_invalid_email_is_422(client, booking_property):
    res = await client.post("/api/tours", json=_body(booking_property, visitorEmail="not-an-email"))
    assert res.status_code == 422


# ---------------- capacity ----------------
async def test_capacity_exact_fill_then_reject_then_free(client, booking_property, admin_auth):
    await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"capacityPerSlot": 2},
        headers=admin_auth,
    )
    d, t = next_open_slot(days_ahead=4)
    p = {
        "propertyId": booking_property,
        "visitorName": "G",
        "visitorPhone": "+2348000000000",
        "scheduledDate": d,
        "scheduledTime": t,
    }
    a = await client.post("/api/tours", json={**p, "visitorEmail": "a@example.com"})
    b = await client.post("/api/tours", json={**p, "visitorEmail": "b@example.com"})
    c = await client.post("/api/tours", json={**p, "visitorEmail": "c@example.com"})
    assert (a.status_code, b.status_code, c.status_code) == (201, 201, 409)

    code = a.json()["confirmationCode"]
    await client.post(
        "/api/tours/cancel", json={"confirmationCode": code, "email": "a@example.com"}
    )
    d2 = await client.post("/api/tours", json={**p, "visitorEmail": "d@example.com"})
    assert d2.status_code == 201


# ---------------- availability ----------------
async def test_availability_past_date_is_empty(client, booking_property):
    res = await client.get(
        f"/api/properties/{booking_property}/availability", params={"on": "2020-01-01"}
    )
    assert res.json()["slots"] == []


async def test_availability_unknown_property_404(client):
    assert (
        await client.get("/api/properties/999999/availability", params={"on": "2030-01-01"})
    ).status_code == 404


# ---------------- lifecycle ----------------
async def test_confirm_cancelled_tour_is_409(client, booking_property, admin_auth):
    await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"autoConfirm": False},
        headers=admin_auth,
    )
    made = await client.post("/api/tours", json=_body(booking_property))
    tid = made.json()["id"]
    await client.request("DELETE", f"/api/tours/{tid}", headers=admin_auth)
    res = await client.post(f"/api/tours/{tid}/confirm", headers=admin_auth)
    assert res.status_code == 409


async def test_confirm_already_confirmed_is_idempotent(client, booking_property, admin_auth):
    made = await client.post("/api/tours", json=_body(booking_property))
    tid = made.json()["id"]
    assert made.json()["status"] == "CONFIRMED"  # default auto-confirm
    again = await client.post(f"/api/tours/{tid}/confirm", headers=admin_auth)
    assert again.status_code == 200
    assert again.json()["status"] == "CONFIRMED"


async def test_cancel_already_cancelled_is_idempotent(client, booking_property):
    made = await client.post("/api/tours", json=_body(booking_property))
    code = made.json()["confirmationCode"]
    a = await client.post(
        "/api/tours/cancel", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    b = await client.post(
        "/api/tours/cancel", json={"confirmationCode": code, "email": "guest@example.com"}
    )
    assert a.status_code == 200 and b.status_code == 200
    assert b.json()["status"] == "CANCELLED"


async def test_guest_lookup_wrong_code_or_email_is_404(client, booking_property):
    made = await client.post("/api/tours", json=_body(booking_property))
    code = made.json()["confirmationCode"]
    assert (
        await client.post(
            "/api/tours/lookup", json={"confirmationCode": code, "email": "wrong@example.com"}
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/tours/lookup",
            json={"confirmationCode": "ZENT-XXXXXX", "email": "guest@example.com"},
        )
    ).status_code == 404


async def test_patch_reschedule_into_full_slot_is_409(client, booking_property, admin_auth):
    d, t1 = next_open_slot(days_ahead=5)
    t2 = "14:00" if t1 != "14:00" else "15:00"
    await client.post(
        "/api/tours", json=_body(booking_property, scheduledDate=d, scheduledTime=t1)
    )
    second = await client.post(
        "/api/tours",
        json=_body(
            booking_property, scheduledDate=d, scheduledTime=t2, visitorEmail="two@example.com"
        ),
    )
    # move #2 onto #1's full slot
    res = await client.patch(
        f"/api/tours/{second.json()['id']}",
        json={"scheduledDate": d, "scheduledTime": t1},
        headers=admin_auth,
    )
    assert res.status_code == 409


async def test_patch_bad_lead_status_is_422(client, booking_property, admin_auth):
    made = await client.post("/api/tours", json=_body(booking_property))
    res = await client.patch(
        f"/api/tours/{made.json()['id']}", json={"leadStatus": "MAYBE"}, headers=admin_auth
    )
    assert res.status_code == 422


# ---------------- schedule config ----------------
async def test_schedule_rejects_invalid_timezone(client, booking_property, admin_auth):
    res = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"timezone": "Mars/Olympus"},
        headers=admin_auth,
    )
    assert res.status_code == 422


async def test_schedule_rejects_bad_ranges_and_capacity(client, booking_property, admin_auth):
    bad_range = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"weeklyHours": {"mon": [["17:00", "10:00"]]}},
        headers=admin_auth,
    )
    assert bad_range.status_code == 422

    bad_cap = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"capacityPerSlot": 0},
        headers=admin_auth,
    )
    assert bad_cap.status_code == 422


async def test_schedule_range_shorter_than_slot_yields_no_slots(
    client, booking_property, admin_auth
):
    d, _ = next_open_slot(days_ahead=6)
    wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][date.fromisoformat(d).weekday()]
    await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"weeklyHours": {wd: [["10:00", "10:30"]]}, "slotDurationMinutes": 60},
        headers=admin_auth,
    )
    res = await client.get(f"/api/properties/{booking_property}/availability", params={"on": d})
    assert res.json()["slots"] == []
