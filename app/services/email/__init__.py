from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.email.base import EmailSender
from app.services.email.console import ConsoleEmailSender
from app.services.email.resend import ResendEmailSender
from app.services.email.smtp import SMTPEmailSender

__all__ = ["EmailSender", "get_email_sender"]


@lru_cache
def get_email_sender() -> EmailSender:
    """Console/log sender unless PROD is true. In prod, Resend's HTTPS API is
    preferred over raw SMTP when configured — several hosts (Render included)
    block outbound SMTP ports on standard tiers. FastAPI dependency."""
    if not settings.PROD:
        return ConsoleEmailSender()
    if settings.resend_configured:
        return ResendEmailSender()
    return SMTPEmailSender()
