from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.email import get_email_sender
from app.services.email.console import ConsoleEmailSender
from app.services.email.resend import ResendEmailSender, ResendError
from app.services.email.smtp import SMTPEmailSender


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(settings, "RESEND_FROM", "Zent <hello@zentbookings.com>")


async def test_resend_send_success(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"id": "abc"}

    async def fake_post(self, url, *, headers=None, json=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await ResendEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>", text="hi")
    assert captured["json"]["from"] == "Zent <hello@zentbookings.com>"
    assert captured["json"]["to"] == ["x@example.com"]
    assert captured["headers"]["Authorization"] == "Bearer re_test_key"


async def test_resend_send_raises_on_error(monkeypatch):
    class _Resp:
        status_code = 422
        headers = {"content-type": "application/json"}

        def json(self):
            return {"message": "domain not verified"}

    async def fake_post(self, url, *, headers=None, json=None):
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ResendError):
        await ResendEmailSender().send(to="x@example.com", subject="s", html="<p>hi</p>")


async def test_get_email_sender_prefers_resend_in_prod(monkeypatch):
    monkeypatch.setattr(settings, "PROD", True)
    get_email_sender.cache_clear()
    try:
        assert isinstance(get_email_sender(), ResendEmailSender)
    finally:
        get_email_sender.cache_clear()


async def test_get_email_sender_falls_back_to_smtp_without_resend(monkeypatch):
    monkeypatch.setattr(settings, "PROD", True)
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    get_email_sender.cache_clear()
    try:
        assert isinstance(get_email_sender(), SMTPEmailSender)
    finally:
        get_email_sender.cache_clear()


async def test_get_email_sender_uses_console_outside_prod(monkeypatch):
    monkeypatch.setattr(settings, "PROD", False)
    get_email_sender.cache_clear()
    try:
        assert isinstance(get_email_sender(), ConsoleEmailSender)
    finally:
        get_email_sender.cache_clear()
