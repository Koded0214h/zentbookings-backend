from __future__ import annotations

from datetime import date, timedelta

from conftest import next_open_slot


async def test_availability_default_schedule(client, booking_property):
    d, _ = next_open_slot()
    res = await client.get(f"/api/properties/{booking_property}/availability", params={"on": d})
    assert res.status_code == 200
    body = res.json()
    assert body["timezone"] == "Africa/Lagos"
    times = [s["time"] for s in body["slots"]]
    assert "10:00" in times and "16:00" in times  # 10-17 hourly, last full slot 16:00
    assert all(s["date"] == d for s in body["slots"])
    assert all(s["capacity"] == 1 and s["available"] == 1 for s in body["slots"])


async def test_availability_sunday_is_empty(client, booking_property):
    d = date.today() + timedelta(days=2)
    while d.weekday() != 6:
        d += timedelta(days=1)
    res = await client.get(
        f"/api/properties/{booking_property}/availability", params={"on": d.isoformat()}
    )
    assert res.json()["slots"] == []


async def test_availability_reflects_bookings(client, booking_property):
    d, t = next_open_slot(days_ahead=8)
    await client.post(
        "/api/tours",
        json={
            "propertyId": booking_property,
            "visitorName": "G",
            "visitorEmail": "g@example.com",
            "visitorPhone": "+2348000000000",
            "scheduledDate": d,
            "scheduledTime": t,
        },
    )
    res = await client.get(f"/api/properties/{booking_property}/availability", params={"on": d})
    slot = next(s for s in res.json()["slots"] if s["time"] == t)
    assert slot["available"] == 0


async def test_blackout_date_removes_slots(client, booking_property, admin_auth):
    d, _ = next_open_slot(days_ahead=9)
    upd = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"blackoutDates": [d]},
        headers=admin_auth,
    )
    assert upd.status_code == 200
    res = await client.get(f"/api/properties/{booking_property}/availability", params={"on": d})
    assert res.json()["slots"] == []


async def test_schedule_is_staff_only(client, booking_property, registered_user):
    token = registered_user["body"]["token"]
    assert (
        await client.get(
            f"/api/properties/{booking_property}/schedule",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).status_code == 403
    anon = await client.get(f"/api/properties/{booking_property}/schedule")
    assert anon.status_code in (401, 403)


async def test_schedule_update_validates(client, booking_property, admin_auth):
    bad_day = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"weeklyHours": {"funday": [["10:00", "12:00"]]}},
        headers=admin_auth,
    )
    assert bad_day.status_code == 422

    bad_range = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"weeklyHours": {"mon": [["17:00", "10:00"]]}},
        headers=admin_auth,
    )
    assert bad_range.status_code == 422

    ok = await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"slotDurationMinutes": 30, "capacityPerSlot": 3},
        headers=admin_auth,
    )
    assert ok.status_code == 200
    assert ok.json()["slotDurationMinutes"] == 30
    assert ok.json()["capacityPerSlot"] == 3


async def test_custom_capacity_allows_multiple(client, booking_property, admin_auth):
    await client.put(
        f"/api/properties/{booking_property}/schedule",
        json={"capacityPerSlot": 2},
        headers=admin_auth,
    )
    d, t = next_open_slot(days_ahead=10)
    payload = {
        "propertyId": booking_property,
        "visitorName": "G",
        "visitorPhone": "+2348000000000",
        "scheduledDate": d,
        "scheduledTime": t,
    }
    r1 = await client.post("/api/tours", json={**payload, "visitorEmail": "a@example.com"})
    r2 = await client.post("/api/tours", json={**payload, "visitorEmail": "b@example.com"})
    r3 = await client.post("/api/tours", json={**payload, "visitorEmail": "c@example.com"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 409
