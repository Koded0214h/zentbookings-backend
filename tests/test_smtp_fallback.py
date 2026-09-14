from __future__ import annotations

import aiosmtplib
import pytest

from app.core.config import settings
from app.services.email.smtp import SMTPEmailSender


@pytest.fixture(autouse=True)
def _configure_smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.primary.test")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_SECURITY", "starttls")
    monkeypatch.setattr(settings, "SMTP_USER", "primary@zentbookings.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "primary-pass")
    monkeypatch.setattr(settings, "SMTP_FROM", "Zent <primary@zentbookings.com>")
    monkeypatch.setattr(settings, "SMTP_FALLBACK_HOST", "smtp.fallback.test")
    monkeypatch.setattr(settings, "SMTP_FALLBACK_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FALLBACK_SECURITY", "starttls")
    monkeypatch.setattr(settings, "SMTP_FALLBACK_USER", "fallback@gmail.com")
    monkeypatch.setattr(settings, "SMTP_FALLBACK_PASSWORD", "fallback-pass")
    monkeypatch.setattr(settings, "SMTP_FALLBACK_FROM", "Zent <fallback@gmail.com>")


async def test_primary_success_never_touches_fallback(monkeypatch):
    calls = []

    async def fake_send(msg, *, hostname, **kw):
        calls.append(hostname)

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await SMTPEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>")
    assert calls == ["smtp.primary.test"]


async def test_falls_back_when_primary_raises(monkeypatch):
    calls = []

    async def fake_send(msg, *, hostname, **kw):
        calls.append(hostname)
        if hostname == "smtp.primary.test":
            raise aiosmtplib.SMTPConnectTimeoutError("timed out")

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await SMTPEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>")
    assert calls == ["smtp.primary.test", "smtp.fallback.test"]


async def test_raises_when_fallback_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FALLBACK_HOST", None)

    async def fake_send(msg, *, hostname, **kw):
        raise aiosmtplib.SMTPConnectTimeoutError("timed out")

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    with pytest.raises(aiosmtplib.SMTPException):
        await SMTPEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>")


async def test_raises_when_both_providers_fail(monkeypatch):
    async def fake_send(msg, *, hostname, **kw):
        raise aiosmtplib.SMTPConnectTimeoutError("timed out")

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    with pytest.raises(aiosmtplib.SMTPException):
        await SMTPEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>")
