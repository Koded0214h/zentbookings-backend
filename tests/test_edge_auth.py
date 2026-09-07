from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from conftest import _extract_otp, _register

from app.core.config import settings
from app.core.security import create_access_token


# ---------------- register / OTP ----------------
async def test_register_normalizes_email_and_trims_names(client, email_sender):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "  Ada  ",
            "lastName": "  Lovelace ",
            "email": "  ADA@Example.COM ",
            "password": "SecurePass123",
        },
    )
    assert res.status_code == 201
    assert res.json()["email"] == "ada@example.com"
    code = _extract_otp(email_sender, "ada@example.com")
    body = (
        await client.post("/api/auth/verify-otp", json={"email": "ada@example.com", "code": code})
    ).json()
    assert body["user"]["firstName"] == "Ada"
    assert body["user"]["fullName"] == "Ada Lovelace"


async def test_register_rejects_whitespace_only_names(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "   ",
            "lastName": "Ok",
            "email": "blank@example.com",
            "password": "SecurePass123",
        },
    )
    assert res.status_code == 422


async def test_register_duplicate_is_case_insensitive(client, registered_user):
    res = await client.post(
        "/api/auth/register",
        json={
            "firstName": "X",
            "lastName": "Y",
            "email": "AMARA@EXAMPLE.COM",
            "password": "SecurePass123",
        },
    )
    assert res.status_code == 409


async def test_verify_otp_expired_code(client, email_sender, session_factory):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "E",
            "lastName": "X",
            "email": "exp@example.com",
            "password": "SecurePass123",
        },
    )
    code = _extract_otp(email_sender, "exp@example.com")

    from sqlalchemy import select

    from app.models.user import EmailOtp, User

    async with session_factory() as db:
        uid = (
            await db.execute(select(User.id).where(User.email == "exp@example.com"))
        ).scalar_one()
        row = await db.get(EmailOtp, uid)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    res = await client.post("/api/auth/verify-otp", json={"email": "exp@example.com", "code": code})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "otp_invalid"


async def test_verify_otp_code_with_whitespace_is_trimmed(client, email_sender):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "W",
            "lastName": "S",
            "email": "ws@example.com",
            "password": "SecurePass123",
        },
    )
    code = _extract_otp(email_sender, "ws@example.com")
    res = await client.post(
        "/api/auth/verify-otp", json={"email": "ws@example.com", "code": f"  {code} "}
    )
    assert res.status_code == 200


async def test_resend_resets_the_attempt_counter(client, email_sender):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "R",
            "lastName": "A",
            "email": "ra@example.com",
            "password": "SecurePass123",
        },
    )
    for _ in range(5):
        await client.post(
            "/api/auth/verify-otp", json={"email": "ra@example.com", "code": "000000"}
        )
    assert (
        await client.post(
            "/api/auth/verify-otp", json={"email": "ra@example.com", "code": "000000"}
        )
    ).status_code == 429

    await client.post("/api/auth/resend-otp", json={"email": "ra@example.com"})
    fresh = _extract_otp(email_sender, "ra@example.com")
    assert (
        await client.post("/api/auth/verify-otp", json={"email": "ra@example.com", "code": fresh})
    ).status_code == 200


# ---------------- login ----------------
async def test_login_email_is_case_insensitive(client, registered_user):
    res = await client.post(
        "/api/auth/login", json={"email": "AMARA@example.com", "password": "SecurePass123"}
    )
    assert res.status_code == 200


async def test_login_deactivated_user(client, registered_user, admin_auth):
    uid = registered_user["body"]["user"]["id"]
    await client.patch(
        f"/api/admin/users/{uid}/status", json={"isActive": False}, headers=admin_auth
    )
    res = await client.post(
        "/api/auth/login", json={"email": "amara@example.com", "password": "SecurePass123"}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


async def test_login_unverified_then_verify_then_login(client, email_sender):
    await client.post(
        "/api/auth/register",
        json={
            "firstName": "U",
            "lastName": "V",
            "email": "uv2@example.com",
            "password": "SecurePass123",
        },
    )
    blocked = await client.post(
        "/api/auth/login", json={"email": "uv2@example.com", "password": "SecurePass123"}
    )
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "email_unverified"

    code = _extract_otp(email_sender, "uv2@example.com")
    await client.post("/api/auth/verify-otp", json={"email": "uv2@example.com", "code": code})
    assert (
        await client.post(
            "/api/auth/login", json={"email": "uv2@example.com", "password": "SecurePass123"}
        )
    ).status_code == 200


# ---------------- JWT / session ----------------
async def test_tampered_token_rejected(client, registered_user):
    tok = registered_user["body"]["token"]
    tampered = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert res.status_code == 401


async def test_expired_token_rejected(client, registered_user):
    uid = registered_user["body"]["user"]["id"]
    now = int(datetime.now(UTC).timestamp())
    stale = jwt.encode(
        {"sub": uid, "iat": now - 100, "exp": now - 10, "jti": "x", "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale}"})
    ).status_code == 401


async def test_token_for_deleted_user(client, email_sender, session_factory):
    body = await _register(client, email_sender, "gone@example.com")
    from sqlalchemy import text

    async with session_factory() as db:
        await db.execute(text("DELETE FROM users WHERE email = 'gone@example.com'"))
        await db.commit()
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert res.status_code == 401


async def test_token_missing_sub(client):
    now = int(datetime.now(UTC).timestamp())
    bad = jwt.encode(
        {"iat": now, "exp": now + 999, "jti": "x", "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert res.status_code == 401


async def test_wrong_scheme_header(client, registered_user):
    tok = registered_user["body"]["token"]
    res = await client.get("/api/auth/me", headers={"Authorization": f"Token {tok}"})
    assert res.status_code in (401, 403)


async def test_logout_is_idempotent(client, registered_user):
    auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    assert (await client.post("/api/auth/logout", headers=auth)).status_code == 200
    # second logout: token already revoked -> get_current_user 401
    assert (await client.post("/api/auth/logout", headers=auth)).status_code == 401


async def test_refresh_twice_revokes_each_prior_token(client, registered_user):
    t0 = registered_user["body"]["token"]
    r1 = await client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {t0}"})
    t1 = r1.json()["token"]
    r2 = await client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {t1}"})
    t2 = r2.json()["token"]

    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {t0}"})
    ).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {t1}"})
    ).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"})
    ).status_code == 200


async def test_stale_token_renew_header_only_past_threshold(client, registered_user):
    uid = registered_user["body"]["user"]["id"]
    # fresh token: no header
    fresh = create_access_token(uid)
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh}"})
    assert "x-renewed-token" not in {k.lower() for k in r.headers}


# ---------------- forgot / reset password ----------------
async def test_forgot_password_unknown_email_is_202(client):
    res = await client.post("/api/auth/forgot-password", json={"email": "nobody@nowhere.com"})
    assert res.status_code == 202


async def test_reset_token_single_use(client, registered_user, email_sender):
    import re

    await client.post("/api/auth/forgot-password", json={"email": "amara@example.com"})
    token = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", email_sender.sent[-1]["html"]).group(1)
    first = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "NewSecurePass1"}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "AnotherPass1"}
    )
    assert second.status_code == 400


async def test_oauth_only_user_cannot_password_login(client, session_factory):
    from app.models.user import User

    async with session_factory() as db:
        db.add(
            User(
                email="oauthonly@example.com",
                hashed_password=None,
                first_name="O",
                last_name="A",
                is_verified=True,
            )
        )
        await db.commit()
    res = await client.post(
        "/api/auth/login", json={"email": "oauthonly@example.com", "password": "whatever123"}
    )
    assert res.status_code == 401
