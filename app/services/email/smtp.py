from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings
from app.services.email.base import EmailSender

logger = logging.getLogger("zent.email")


class SMTPEmailSender(EmailSender):
    """Production sender over SMTP (Resend / SendGrid / Postmark / any SMTP relay)."""

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text or "This message requires an HTML-capable email client.")
        msg.add_alternative(html, subtype="html")

        security = settings.SMTP_SECURITY.lower()
        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                use_tls=security == "ssl",       # implicit TLS, e.g. port 465
                start_tls=security == "starttls",  # STARTTLS upgrade, e.g. port 587
            )
        except aiosmtplib.SMTPException:
            logger.exception("[email:smtp] failed to send to=%s subject=%s", to, subject)
            raise
