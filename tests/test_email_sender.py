from app.core.config import settings
from app.services.email import get_email_sender
from app.services.email.console import ConsoleEmailSender
from app.services.email.smtp import SMTPEmailSender


async def test_get_email_sender_uses_smtp_in_prod(monkeypatch):
    monkeypatch.setattr(settings, "PROD", True)
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
