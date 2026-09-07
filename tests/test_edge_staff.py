from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import _register, sample_property


# ---------------- roles ----------------
async def test_promote_to_unknown_role_is_422(client, admin_auth, registered_user):
    uid = registered_user["body"]["user"]["id"]
    res = await client.patch(
        f"/api/admin/users/{uid}/role", json={"role": "manager"}, headers=admin_auth
    )
    assert res.status_code == 422


async def test_set_role_missing_user_404(client, admin_auth):
    res = await client.patch(
        "/api/admin/users/usr_missing/role", json={"role": "agent"}, headers=admin_auth
    )
    assert res.status_code == 404


async def test_admin_to_admin_role_is_allowed(client, admin_auth):
    r = await client.get("/api/admin/users", params={"role": "admin"}, headers=admin_auth)
    aid = r.json()["users"][0]["id"]
    res = await client.patch(
        f"/api/admin/users/{aid}/role", json={"role": "admin"}, headers=admin_auth
    )
    assert res.status_code == 200


async def test_second_admin_lets_first_be_demoted(
    client, admin_auth, email_sender, session_factory
):
    from conftest import _set_role

    await _register(client, email_sender, "admin2@example.com", "Ad", "Two")
    await _set_role(session_factory, "admin2@example.com", "admin")

    r = await client.get("/api/admin/users", params={"role": "admin"}, headers=admin_auth)
    first = next(u for u in r.json()["users"] if u["email"] != "admin2@example.com")
    res = await client.patch(
        f"/api/admin/users/{first['id']}/role", json={"role": "user"}, headers=admin_auth
    )
    assert res.status_code == 200


async def test_invite_with_non_staff_role_is_422(client, admin_auth):
    res = await client.post(
        "/api/admin/agents/invite",
        json={"firstName": "N", "lastName": "S", "email": "ns@example.com", "role": "user"},
        headers=admin_auth,
    )
    assert res.status_code == 422


# ---------------- attendance ----------------
async def test_clock_out_without_clock_in_is_409(client, agent_auth):
    res = await client.post("/api/staff/clock-out", headers=agent_auth["headers"])
    assert res.status_code == 409


async def test_status_when_never_clocked_in(client, agent_auth):
    res = await client.get("/api/staff/me/status", headers=agent_auth["headers"])
    body = res.json()
    assert body["clockedIn"] is False
    assert body["since"] is None
    assert body["todayMinutes"] == 0


async def test_admin_edit_attendance_rejects_out_of_order_times(client, admin_auth, agent_auth):
    h = agent_auth["headers"]
    await client.post("/api/staff/clock-in", json={}, headers=h)
    rec = (await client.get("/api/staff/attendance/me", headers=h)).json()["records"][0]["id"]

    now = datetime.now(UTC)
    res = await client.patch(
        f"/api/admin/attendance/{rec}",
        json={
            "clockInAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clockOutAt": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        headers=admin_auth,
    )
    assert res.status_code == 409


async def test_admin_edit_missing_attendance_404(client, admin_auth):
    res = await client.patch(
        "/api/admin/attendance/att_missing", json={"note": "x"}, headers=admin_auth
    )
    assert res.status_code == 404


async def test_auto_close_boundary(client, agent_auth, session_factory):
    from sqlalchemy import select

    from app.models.staff import StaffAttendance
    from app.services.attendance_service import close_stale

    async with session_factory() as db:
        db.add_all(
            [
                StaffAttendance(
                    user_id=agent_auth["id"],
                    clock_in_at=datetime.now(UTC) - timedelta(hours=15, minutes=59),
                ),
            ]
        )
        await db.commit()
    async with session_factory() as db:
        closed = await close_stale(db, older_than_hours=16)
        await db.commit()
    assert closed == 0  # 15h59m < 16h -> stays open

    async with session_factory() as db:
        (await db.execute(select(StaffAttendance))).scalar_one().clock_in_at = datetime.now(
            UTC
        ) - timedelta(hours=17)
        await db.commit()
    async with session_factory() as db:
        assert await close_stale(db, older_than_hours=16) == 1
        await db.commit()


# ---------------- agent assignment ----------------
async def test_assign_to_missing_property_404(client, admin_auth, agent_auth):
    res = await client.post(
        "/api/admin/properties/999999/agents",
        json={"agentId": agent_auth["id"]},
        headers=admin_auth,
    )
    assert res.status_code == 404


async def test_assign_missing_agent_422(client, admin_auth):
    from conftest import sample_property as sp

    pid = (await client.post("/api/properties", json=sp(), headers=admin_auth)).json()["id"]
    res = await client.post(
        f"/api/admin/properties/{pid}/agents", json={"agentId": "usr_ghost"}, headers=admin_auth
    )
    assert res.status_code == 422


async def test_double_assign_is_idempotent(client, admin_auth, agent_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    for _ in range(2):
        r = await client.post(
            f"/api/admin/properties/{pid}/agents",
            json={"agentId": agent_auth["id"]},
            headers=admin_auth,
        )
        assert r.status_code == 201
    got = await client.get(f"/api/admin/properties/{pid}/agents", headers=admin_auth)
    assert got.json()["agentIds"] == [agent_auth["id"]]


async def test_unassign_missing_is_noop(client, admin_auth, agent_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    res = await client.delete(
        f"/api/admin/properties/{pid}/agents/{agent_auth['id']}", headers=admin_auth
    )
    assert res.status_code == 204


async def test_agent_views_empty_without_assignments(client, agent_auth):
    assert (await client.get("/api/agent/properties", headers=agent_auth["headers"])).json() == []
    assert (await client.get("/api/agent/tours", headers=agent_auth["headers"])).json()[
        "total"
    ] == 0


# ---------------- agent public profile ----------------
async def test_public_agent_404_for_non_staff_or_unpublished(client, registered_user, agent_auth):
    # a normal user id
    uid = registered_user["body"]["user"]["id"]
    assert (await client.get(f"/api/agents/{uid}")).status_code == 404
    # staff but unpublished
    assert (await client.get(f"/api/agents/{agent_auth['id']}")).status_code == 404


async def test_unpublishing_removes_from_public_directory(client, agent_auth):
    h = agent_auth["headers"]
    await client.put(
        "/api/staff/me/profile", json={"title": "Advisor", "published": True}, headers=h
    )
    assert len((await client.get("/api/agents")).json()["agents"]) == 1

    await client.put("/api/staff/me/profile", json={"published": False}, headers=h)
    assert (await client.get("/api/agents")).json()["agents"] == []
