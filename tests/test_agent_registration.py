from __future__ import annotations

import re

import pytest

from app.core.config import settings
from app.services import nin_verification
from app.services.nin_verification import NinResult, NinVerificationFailed


def _body(**over) -> dict:
    body = {
        "firstName": "Ada",
        "lastName": "Agent",
        "email": "ada.agent@example.com",
        "password": "SecurePass123",
        "nin": "12345678901",
    }
    body.update(over)
    return body


@pytest.fixture
def fake_nin_pass(monkeypatch):
    async def verify(nin: str, *, first_name: str, last_name: str) -> NinResult:
        return NinResult(registered_name=f"{first_name} {last_name}", reference=nin)

    monkeypatch.setattr(nin_verification, "verify_nin", verify)


@pytest.fixture
def fake_nin_fail(monkeypatch):
    async def verify(nin: str, *, first_name: str, last_name: str) -> NinResult:
        raise NinVerificationFailed("No record found for that NIN.")

    monkeypatch.setattr(nin_verification, "verify_nin", verify)


async def test_register_agent_without_provider_configured_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_APP_ID", None)
    monkeypatch.setattr(settings, "DOJAH_SECRET_KEY", None)
    res = await client.post("/api/auth/register-agent", json=_body())
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "nin_not_configured"


async def test_register_agent_bad_nin_format_is_422(client):
    res = await client.post("/api/auth/register-agent", json=_body(nin="123"))
    assert res.status_code == 422


async def test_register_agent_success_end_to_end(client, email_sender, fake_nin_pass):
    res = await client.post("/api/auth/register-agent", json=_body())
    assert res.status_code == 201, res.text
    assert "verification code" in res.json()["message"].lower()

    sent = [s for s in email_sender.sent if s["to"] == "ada.agent@example.com"]
    assert sent
    code = re.search(r"\b(\d{6})\b", sent[-1]["text"] or sent[-1]["html"]).group(1)

    verified = await client.post(
        "/api/auth/verify-otp", json={"email": "ada.agent@example.com", "code": code}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["user"]["role"] == "agent"

    login = await client.post(
        "/api/auth/login", json={"email": "ada.agent@example.com", "password": "SecurePass123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "agent"


async def test_register_agent_nin_verification_failed_creates_no_account(
    client, fake_nin_fail
):
    res = await client.post("/api/auth/register-agent", json=_body())
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "nin_verification_failed"

    # no account was created -> a normal login attempt fails as unknown user
    login = await client.post(
        "/api/auth/login", json={"email": "ada.agent@example.com", "password": "SecurePass123"}
    )
    assert login.status_code == 401


async def test_register_agent_duplicate_email_is_409(client, fake_nin_pass):
    first = await client.post("/api/auth/register-agent", json=_body())
    assert first.status_code == 201
    second = await client.post("/api/auth/register-agent", json=_body())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "email_exists"


async def test_register_agent_duplicate_nin_is_409(client, fake_nin_pass):
    first = await client.post("/api/auth/register-agent", json=_body())
    assert first.status_code == 201
    second = await client.post(
        "/api/auth/register-agent", json=_body(email="other.agent@example.com")
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "nin_exists"
