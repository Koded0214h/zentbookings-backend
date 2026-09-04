from __future__ import annotations

from conftest import _extract_otp


async def _register_raw(client, email: str) -> None:
    res = await client.post(
        "/api/auth/register",
        json={"firstName": "O", "lastName": "T", "email": email, "password": "SecurePass123"},
    )
    assert res.status_code == 201, res.text


async def test_verify_otp_happy_path_logs_in(client, email_sender):
    email = "otp@example.com"
    await _register_raw(client, email)
    code = _extract_otp(email_sender, email)

    res = await client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token"]
    assert body["user"]["isVerified"] is True

    # now login works
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    assert login.status_code == 200


async def test_verify_otp_wrong_code_is_rejected(client, email_sender):
    email = "otpwrong@example.com"
    await _register_raw(client, email)

    res = await client.post("/api/auth/verify-otp", json={"email": email, "code": "000000"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "otp_invalid"

    # the real code still works afterward
    code = _extract_otp(email_sender, email)
    ok = await client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert ok.status_code == 200


async def test_verify_otp_locks_after_max_attempts(client, email_sender):
    email = "otplock@example.com"
    await _register_raw(client, email)

    for _ in range(5):
        res = await client.post("/api/auth/verify-otp", json={"email": email, "code": "000000"})
        assert res.status_code == 400

    locked = await client.post("/api/auth/verify-otp", json={"email": email, "code": "000000"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "otp_locked"

    # even the correct code is now locked out until a resend
    code = _extract_otp(email_sender, email)
    still_locked = await client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert still_locked.status_code == 429


async def test_verify_otp_unknown_email(client):
    res = await client.post(
        "/api/auth/verify-otp", json={"email": "ghost@example.com", "code": "123456"}
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "otp_invalid"


async def test_verify_otp_already_verified_is_idempotent(client, registered_user):
    email = registered_user["payload"]["email"]
    res = await client.post(
        "/api/auth/verify-otp", json={"email": email, "code": "999999"}
    )
    assert res.status_code == 200
    assert res.json()["user"]["isVerified"] is True


async def test_resend_otp_issues_a_new_working_code(client, email_sender):
    email = "resend@example.com"
    await _register_raw(client, email)
    first_code = _extract_otp(email_sender, email)

    res = await client.post("/api/auth/resend-otp", json={"email": email})
    assert res.status_code == 202

    second_code = _extract_otp(email_sender, email)

    # resend overwrites the code, so the old one is now invalid (independently random,
    # so this could theoretically coincide with the new one — odds are 1 in a million)
    stale = await client.post(
        "/api/auth/verify-otp", json={"email": email, "code": first_code}
    )
    assert stale.status_code == 400

    ok = await client.post("/api/auth/verify-otp", json={"email": email, "code": second_code})
    assert ok.status_code == 200


async def test_resend_otp_is_silent_for_unknown_or_verified_email(client, registered_user):
    unknown = await client.post("/api/auth/resend-otp", json={"email": "nobody@example.com"})
    assert unknown.status_code == 202

    verified = await client.post(
        "/api/auth/resend-otp", json={"email": registered_user["payload"]["email"]}
    )
    assert verified.status_code == 202
