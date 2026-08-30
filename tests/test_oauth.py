from __future__ import annotations

import pytest

from app.services import auth_service, oauth


async def test_google_start_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_SECRET", None)
    res = await client.get(
        "/api/auth/google",
        params={"redirect_uri": "https://zentbookings.com/"},
        follow_redirects=False,
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "oauth_not_configured"


async def test_google_start_redirects_when_configured(client, monkeypatch):
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_SECRET", "test-secret")

    res = await client.get(
        "/api/auth/google",
        params={"redirect_uri": "https://zentbookings.com/"},
        follow_redirects=False,
    )
    assert res.status_code == 307
    assert res.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )
    assert "code_challenge=" in res.headers["location"]


async def test_disallowed_redirect_host_rejected(client, monkeypatch):
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_SECRET", "test-secret")

    res = await client.get(
        "/api/auth/google",
        params={"redirect_uri": "https://evil.example.com/"},
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "oauth_failed"


async def test_google_callback_creates_and_links_user(client, monkeypatch, session_factory):
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oauth.settings, "GOOGLE_CLIENT_SECRET", "test-secret")

    # seed a valid flow row directly
    async with session_factory() as db:
        state, _ = await oauth.create_state(
            db, provider="google", redirect_uri="https://zentbookings.com/"
        )
        await db.commit()

    async def fake_profile(*, code, code_verifier):
        return {
            "account_id": "google-sub-123",
            "email": "oauthuser@example.com",
            "first_name": "OAuth",
            "last_name": "User",
            "avatar_url": "https://cdn.example.com/a.jpg",
        }

    monkeypatch.setattr(oauth, "google_fetch_profile", fake_profile)

    res = await client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "auth-code"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://zentbookings.com/?token=")

    token = location.split("token=", 1)[1]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "oauthuser@example.com"


async def test_google_callback_rejects_unknown_state(client):
    res = await client.get(
        "/api/auth/google/callback",
        params={"state": "made-up", "code": "x"},
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "oauth_failed"


@pytest.mark.parametrize("provider", ["google", "apple"])
async def test_oauth_account_dedupes_by_provider_id(session_factory, provider):
    async with session_factory() as db:
        u1 = await auth_service.upsert_oauth_user(
            db, provider=provider, account_id="acct-1", email="dedupe@example.com"
        )
        await db.commit()
        u2 = await auth_service.upsert_oauth_user(
            db, provider=provider, account_id="acct-1", email="dedupe@example.com"
        )
        await db.commit()
    assert u1.id == u2.id
