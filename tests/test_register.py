from __future__ import annotations


async def test_register_returns_token_and_user(client, email_sender):
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
    assert body["token"]
    assert body["user"]["email"] == "amara@example.com"
    assert body["user"]["fullName"] == "Amara Adeyemi"
    assert body["user"]["id"].startswith("usr_")
    assert "password" not in body["user"]
    # welcome email queued as a background task
    assert email_sender.sent and email_sender.sent[0]["to"] == "amara@example.com"


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
