from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.email.base import EmailSender
from app.services.email.console import ConsoleEmailSender
from app.services.email.smtp import SMTPEmailSender

__all__ = ["EmailSender", "get_email_sender"]


@lru_cache
def get_email_sender() -> EmailSender:
    """SMTP when PROD is true, otherwise a console/log sender. FastAPI dependency."""
    if settings.PROD:
        return SMTPEmailSender()
    return ConsoleEmailSender()
