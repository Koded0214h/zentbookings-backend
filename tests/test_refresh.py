from __future__ import annotations

import time

import jwt

from app.core import security
from app.core.config import settings


async def test_refresh_returns_new_token_and_revokes_old(client, registered_user):
    old = registered_user["body"]["token"]
    auth = {"Authorization": f"Bearer {old}"}

    res = await client.post("/api/auth/refresh", headers=auth)
    assert res.status_code == 200
    new = res.json()["token"]
    assert new and new != old

    # new token works, old token is now revoked
    new_auth = {"Authorization": f"Bearer {new}"}
    assert (await client.get("/api/auth/me", headers=new_auth)).status_code == 200
    assert (await client.get("/api/auth/me", headers=auth)).status_code == 401


async def test_refresh_requires_auth(client):
    assert (await client.post("/api/auth/refresh")).status_code in (401, 403)


async def test_stale_token_gets_renewed_header(client, registered_user, monkeypatch):
    user_id = registered_user["body"]["user"]["id"]

    # forge a token that is already 90% through its lifetime
    now = int(time.time())
    lifetime = settings.ACCESS_TOKEN_EXPIRE_DAYS * 86400
    payload = {
        "sub": user_id,
        "iat": now - int(lifetime * 0.9),
        "exp": now + int(lifetime * 0.1),
        "jti": "stale-jti",
        "type": "access",
    }
    stale = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale}"})
    assert res.status_code == 200
    assert "X-Renewed-Token" in res.headers
    # the renewed token is valid and distinct
    renewed = res.headers["X-Renewed-Token"]
    decoded = security.decode_access_token(renewed)
    assert decoded["sub"] == user_id
    assert decoded["jti"] != "stale-jti"


async def test_fresh_token_has_no_renew_header(client, registered_user):
    token = registered_user["body"]["token"]
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "X-Renewed-Token" not in res.headers
