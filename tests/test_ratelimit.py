from __future__ import annotations

from app.core import ratelimit


async def test_login_rate_limited_after_threshold(client):
    # LOGIN_RATE_LIMIT is bound at import (default "10/60"): wrong creds -> 401
    # up to the limit, then 429.
    body = {"email": "nobody@example.com", "password": "whatever1"}
    limit, _ = ratelimit.parse_rule(ratelimit.settings.LOGIN_RATE_LIMIT)

    statuses = [
        (await client.post("/api/auth/login", json=body)).status_code
        for _ in range(limit + 5)
    ]
    assert statuses[:limit] == [401] * limit
    assert statuses[limit] == 429

    limited = await client.post("/api/auth/login", json=body)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in limited.headers


async def test_rate_limit_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "RATE_LIMIT_ENABLED", False)
    body = {"email": "nobody@example.com", "password": "whatever1"}
    for _ in range(30):
        r = await client.post("/api/auth/login", json=body)
        assert r.status_code == 401


async def test_register_and_login_limits_are_separate_buckets(client, monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "RATE_LIMIT_ENABLED", True)
    # exhaust login bucket
    for _ in range(40):
        await client.post(
            "/api/auth/login", json={"email": "x@y.com", "password": "whatever1"}
        )
    # register still works
    r = await client.post(
        "/api/auth/register",
        json={
            "firstName": "Fresh",
            "lastName": "User",
            "email": "fresh@example.com",
            "password": "SecurePass123",
        },
    )
    assert r.status_code == 201
