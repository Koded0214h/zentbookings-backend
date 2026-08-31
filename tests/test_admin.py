from __future__ import annotations

import re

from conftest import _register


async def _admin_id(client, admin_auth) -> str:
    r = await client.get("/api/admin/users", params={"role": "admin"}, headers=admin_auth)
    return r.json()["users"][0]["id"]


async def test_admin_endpoints_reject_non_admin(client, registered_user, agent_auth):
    user_auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    assert (await client.get("/api/admin/users", headers=user_auth)).status_code == 403
    assert (await client.get("/api/admin/users", headers=agent_auth["headers"])).status_code == 403
    assert (await client.get("/api/admin/users")).status_code in (401, 403)


async def test_admin_lists_and_filters_users(client, admin_auth, agent_auth, registered_user):
    res = await client.get("/api/admin/users", headers=admin_auth)
    assert res.status_code == 200
    emails = {u["email"] for u in res.json()["users"]}
    assert {"admin@example.com", "agent@example.com", "amara@example.com"} <= emails

    agents = await client.get("/api/admin/users", params={"role": "agent"}, headers=admin_auth)
    assert [u["email"] for u in agents.json()["users"]] == ["agent@example.com"]

    q = await client.get("/api/admin/users", params={"q": "amara"}, headers=admin_auth)
    assert q.json()["total"] == 1


async def test_change_role_and_audit(client, admin_auth, registered_user):
    uid = registered_user["body"]["user"]["id"]
    res = await client.patch(
        f"/api/admin/users/{uid}/role", json={"role": "agent"}, headers=admin_auth
    )
    assert res.status_code == 200
    assert res.json()["role"] == "agent"

    audit = await client.get(
        "/api/admin/audit", params={"action": "role.change"}, headers=admin_auth
    )
    entries = audit.json()["entries"]
    assert entries and entries[0]["targetId"] == uid
    assert entries[0]["metadata"] == {"from": "user", "to": "agent"}


async def test_last_admin_guard(client, admin_auth):
    aid = await _admin_id(client, admin_auth)
    demote = await client.patch(
        f"/api/admin/users/{aid}/role", json={"role": "user"}, headers=admin_auth
    )
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "last_admin"

    deactivate = await client.patch(
        f"/api/admin/users/{aid}/status", json={"isActive": False}, headers=admin_auth
    )
    assert deactivate.status_code == 409


async def test_deactivate_blocks_the_user(client, admin_auth):
    body = await _register(client, "victim@example.com")
    uid = body["user"]["id"]
    vauth = {"Authorization": f"Bearer {body['token']}"}
    assert (await client.get("/api/auth/me", headers=vauth)).status_code == 200

    off = await client.patch(
        f"/api/admin/users/{uid}/status", json={"isActive": False}, headers=admin_auth
    )
    assert off.status_code == 200
    assert (await client.get("/api/auth/me", headers=vauth)).status_code == 401


async def test_invite_agent_flow(client, admin_auth, email_sender):
    res = await client.post(
        "/api/admin/agents/invite",
        json={
            "firstName": "Ivy",
            "lastName": "Invitee",
            "email": "ivy@example.com",
            "role": "agent",
        },
        headers=admin_auth,
    )
    assert res.status_code == 201, res.text
    assert res.json()["role"] == "agent"

    sent = email_sender.sent[-1]
    assert sent["to"] == "ivy@example.com"
    token = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", sent["html"]).group(1)

    setpw = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "BrandNewPass123"}
    )
    assert setpw.status_code == 200

    login = await client.post(
        "/api/auth/login", json={"email": "ivy@example.com", "password": "BrandNewPass123"}
    )
    assert login.status_code == 200

    dup = await client.post(
        "/api/admin/agents/invite",
        json={"firstName": "I", "lastName": "I", "email": "ivy@example.com"},
        headers=admin_auth,
    )
    assert dup.status_code == 409


async def test_property_delete_is_admin_only(client, admin_auth, agent_auth):
    from conftest import sample_property

    created = await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    pid = created.json()["id"]

    denied = await client.delete(f"/api/properties/{pid}", headers=agent_auth["headers"])
    assert denied.status_code == 403

    ok = await client.delete(f"/api/properties/{pid}", headers=admin_auth)
    assert ok.status_code == 204
