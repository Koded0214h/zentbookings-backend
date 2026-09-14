from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings
from app.services.email.base import EmailSender

logger = logging.getLogger("zent.email")


def _build_message(
    *, from_addr: str, to: str, subject: str, html: str, text: str | None
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text or "This message requires an HTML-capable email client.")
    msg.add_alternative(html, subtype="html")
    return msg


class SMTPEmailSender(EmailSender):
    """Production sender over SMTP (Resend / SendGrid / Postmark / any SMTP relay).

    Falls back to a second provider (`SMTP_FALLBACK_*`) if the primary one
    raises — guards against one provider's transient outages/timeouts taking
    down all outbound mail (OTP codes, booking/tour confirmations, ...).
    """

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        try:
            await self._send_via(
                host=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                security=settings.SMTP_SECURITY,
                user=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                from_addr=settings.SMTP_FROM,
                to=to,
                subject=subject,
                html=html,
                text=text,
            )
        except aiosmtplib.SMTPException:
            logger.warning(
                "[email:smtp] primary send failed to=%s subject=%s", to, subject, exc_info=True
            )
            if not settings.smtp_fallback_configured:
                raise
            try:
                await self._send_via(
                    host=settings.SMTP_FALLBACK_HOST,
                    port=settings.SMTP_FALLBACK_PORT,
                    security=settings.SMTP_FALLBACK_SECURITY,
                    user=settings.SMTP_FALLBACK_USER,
                    password=settings.SMTP_FALLBACK_PASSWORD,
                    from_addr=settings.SMTP_FALLBACK_FROM or settings.SMTP_FROM,
                    to=to,
                    subject=subject,
                    html=html,
                    text=text,
                )
                logger.info("[email:smtp] fallback provider sent to=%s subject=%s", to, subject)
            except aiosmtplib.SMTPException:
                logger.exception(
                    "[email:smtp] fallback send also failed to=%s subject=%s", to, subject
                )
                raise

    async def _send_via(
        self,
        *,
        host: str | None,
        port: int,
        security: str,
        user: str | None,
        password: str | None,
        from_addr: str,
        to: str,
        subject: str,
        html: str,
        text: str | None,
    ) -> None:
        msg = _build_message(from_addr=from_addr, to=to, subject=subject, html=html, text=text)
        sec = security.lower()
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=user,
            password=password,
            use_tls=sec == "ssl",       # implicit TLS, e.g. port 465
            start_tls=sec == "starttls",  # STARTTLS upgrade, e.g. port 587
        )
