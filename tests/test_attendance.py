from __future__ import annotations

from datetime import UTC, datetime, timedelta


async def test_clock_in_requires_staff(client, registered_user):
    auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    assert (await client.post("/api/staff/clock-in", json={}, headers=auth)).status_code == 403


async def test_clock_in_out_cycle(client, agent_auth):
    h = agent_auth["headers"]

    r = await client.post("/api/staff/clock-in", json={"source": "web"}, headers=h)
    assert r.status_code == 201
    assert r.json()["clockOutAt"] is None

    again = await client.post("/api/staff/clock-in", json={}, headers=h)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "attendance_state"

    status = await client.get("/api/staff/me/status", headers=h)
    assert status.json()["clockedIn"] is True
    assert status.json()["since"] is not None

    out = await client.post("/api/staff/clock-out", headers=h)
    assert out.status_code == 200
    assert out.json()["clockOutAt"] is not None
    assert out.json()["durationMinutes"] is not None

    assert (await client.post("/api/staff/clock-out", headers=h)).status_code == 409

    hist = await client.get("/api/staff/attendance/me", headers=h)
    assert hist.json()["total"] == 1


async def test_admin_attendance_views(client, admin_auth, agent_auth):
    h = agent_auth["headers"]
    await client.post("/api/staff/clock-in", json={}, headers=h)
    await client.post("/api/staff/clock-out", headers=h)

    listing = await client.get("/api/admin/attendance", headers=admin_auth)
    assert listing.json()["total"] == 1
    rec = listing.json()["records"][0]
    assert rec["userId"] == agent_auth["id"]

    closed = await client.get(
        "/api/admin/attendance", params={"status": "closed"}, headers=admin_auth
    )
    assert closed.json()["total"] == 1

    summary = await client.get("/api/admin/attendance/summary", headers=admin_auth)
    rows = summary.json()["rows"]
    assert rows and rows[0]["userId"] == agent_auth["id"]
    assert rows[0]["totalMinutes"] >= 0
    assert rows[0]["sessions"] == 1


async def test_admin_edit_attendance(client, admin_auth, agent_auth):
    h = agent_auth["headers"]
    await client.post("/api/staff/clock-in", json={}, headers=h)
    rec_id = (await client.get("/api/staff/attendance/me", headers=h)).json()["records"][0]["id"]

    ci = datetime.now(UTC) - timedelta(hours=3)
    co = datetime.now(UTC) - timedelta(hours=1)
    res = await client.patch(
        f"/api/admin/attendance/{rec_id}",
        json={
            "clockInAt": ci.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clockOutAt": co.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": "fixed a forgotten clock-out",
        },
        headers=admin_auth,
    )
    assert res.status_code == 200
    assert res.json()["durationMinutes"] == 120
    assert res.json()["note"] == "fixed a forgotten clock-out"


async def test_auto_close_stale_sessions(client, agent_auth, session_factory):
    from app.models.staff import StaffAttendance
    from app.services.attendance_service import close_stale

    async with session_factory() as db:
        db.add(
            StaffAttendance(
                user_id=agent_auth["id"],
                clock_in_at=datetime.now(UTC) - timedelta(hours=30),
            )
        )
        await db.commit()

    async with session_factory() as db:
        closed = await close_stale(db, older_than_hours=16)
        await db.commit()
    assert closed == 1

    async with session_factory() as db:
        from sqlalchemy import select

        row = (await db.execute(select(StaffAttendance))).scalar_one()
    assert row.auto_closed is True
    assert row.clock_out_at is not None
    assert row.duration_minutes == 16 * 60
