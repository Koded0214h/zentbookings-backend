from __future__ import annotations


async def test_login_success(client, registered_user):
    res = await client.post(
        "/api/auth/login",
        json={"email": "amara@example.com", "password": "SecurePass123"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["token"]


async def test_login_wrong_password(client, registered_user):
    res = await client.post(
        "/api/auth/login",
        json={"email": "amara@example.com", "password": "WrongPass123"},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


async def test_login_unknown_email(client):
    res = await client.post(
        "/api/auth/login",
        json={"email": "ghost@example.com", "password": "Whatever123"},
    )
    assert res.status_code == 401


async def test_me_requires_token(client):
    res = await client.get("/api/auth/me")
    assert res.status_code in (401, 403)


async def test_me_returns_profile(client, registered_user):
    token = registered_user["body"]["token"]
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == "amara@example.com"
    assert body["fullName"] == "Amara Adeyemi"
    assert body["createdAt"].endswith("Z")


async def test_logout_revokes_token(client, registered_user):
    token = registered_user["body"]["token"]
    auth = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/auth/me", headers=auth)).status_code == 200

    out = await client.post("/api/auth/logout", headers=auth)
    assert out.status_code == 200

    after = await client.get("/api/auth/me", headers=auth)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "unauthorized"


async def test_me_rejects_garbage_token(client):
    res = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert res.status_code == 401
