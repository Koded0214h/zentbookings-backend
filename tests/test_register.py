from __future__ import annotations

from conftest import _extract_otp


async def test_register_creates_unverified_user_no_token_yet(client, email_sender):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "Amara",
            "lastName": "Adeyemi",
            "email": "Amara@Example.com",
            "password": "SecurePass123",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert "token" not in body
    assert body["email"] == "amara@example.com"
    assert body["expiresInSeconds"] > 0

    # otp email queued as a background task
    sent = email_sender.sent[-1]
    assert sent["to"] == "amara@example.com"
    assert "verification code" in sent["subject"].lower()

    # can't log in until verified
    login = await client.post(
        "/api/auth/login", json={"email": "amara@example.com", "password": "SecurePass123"}
    )
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "email_unverified"


async def test_register_duplicate_email_conflicts(client, registered_user):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "Other",
            "lastName": "Person",
            "email": "amara@example.com",
            "password": "AnotherPass123",
        },
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_exists"


async def test_register_rejects_weak_password(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "Weak",
            "lastName": "Pass",
            "email": "weak@example.com",
            "password": "short",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


async def test_register_rejects_password_without_number(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "No",
            "lastName": "Digits",
            "email": "nodigits@example.com",
            "password": "onlyletters",
        },
    )
    assert res.status_code == 422


async def test_registered_user_fixture_is_fully_verified_and_logged_in(client, registered_user):
    """Sanity check on the shared fixture other test files rely on."""
    token = registered_user["body"]["token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["isVerified"] is True


async def test_otp_extractor_finds_the_code(client, email_sender):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "Ex",
            "lastName": "Tract",
            "email": "extract@example.com",
            "password": "SecurePass123",
        },
    )
    code = _extract_otp(email_sender, "extract@example.com")
    assert len(code) == 6 and code.isdigit()
