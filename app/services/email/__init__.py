from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.email.base import EmailSender
from app.services.email.console import ConsoleEmailSender
from app.services.email.smtp import SMTPEmailSender

__all__ = ["EmailSender", "get_email_sender"]


@lru_cache
def get_email_sender() -> EmailSender:
    """Console/log sender locally and SMTP in production. FastAPI dependency."""
    if not settings.PROD:
        return ConsoleEmailSender()
    return SMTPEmailSender()
