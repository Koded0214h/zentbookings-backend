from __future__ import annotations

import re


def _extract_token(html: str) -> str:
    match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", html)
    assert match
    return match.group(1)


async def test_verify_email_with_token_from_welcome_email(client, email_sender):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "Nadia",
            "lastName": "Bello",
            "email": "nadia@example.com",
            "password": "SecurePass123",
        },
    )
    raw_token = _extract_token(email_sender.sent[-1]["html"])

    res = await client.get("/api/auth/verify-email", params={"token": raw_token})
    assert res.status_code == 200
    assert res.json()["message"] == "Email confirmed."

    # single use
    again = await client.get("/api/auth/verify-email", params={"token": raw_token})
    assert again.status_code == 400


async def test_verify_email_rejects_bad_token(client):
    res = await client.get("/api/auth/verify-email", params={"token": "nope"})
    assert res.status_code == 400
