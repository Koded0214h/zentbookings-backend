from __future__ import annotations

import re


def _extract_token(html: str) -> str:
    match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", html)
    assert match, f"no token in email: {html}"
    return match.group(1)


async def test_forgot_password_always_accepts(client):
    res = await client.post(
        "/api/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert res.status_code == 202
    assert "reset link" in res.json()["message"].lower()


async def test_reset_password_end_to_end(client, registered_user, email_sender):
    forgot = await client.post(
        "/api/auth/forgot-password", json={"email": "amara@example.com"}
    )
    assert forgot.status_code == 202

    reset_email = email_sender.sent[-1]
    assert "reset" in reset_email["subject"].lower()
    raw_token = _extract_token(reset_email["html"])

    reset = await client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "BrandNewPass123"},
    )
    assert reset.status_code == 200, reset.text

    # old password no longer works, new one does
    old = await client.post(
        "/api/auth/login",
        json={"email": "amara@example.com", "password": "SecurePass123"},
    )
    assert old.status_code == 401

    new = await client.post(
        "/api/auth/login",
        json={"email": "amara@example.com", "password": "BrandNewPass123"},
    )
    assert new.status_code == 200

    # token is single-use
    replay = await client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "YetAnother123"},
    )
    assert replay.status_code == 400


async def test_reset_password_rejects_unknown_token(client):
    res = await client.post(
        "/api/auth/reset-password",
        json={"token": "totally-made-up", "password": "Whatever123"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_token"
