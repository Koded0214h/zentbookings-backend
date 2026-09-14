from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.services.email.base import EmailSender

logger = logging.getLogger("zent.email")

API_URL = "https://api.resend.com/emails"


class ResendError(Exception):
    pass


class ResendEmailSender(EmailSender):
    """Sends over Resend's HTTPS API instead of raw SMTP.

    Exists because several PaaS hosts (Render included) block outbound SMTP
    ports (25/465/587) on their standard tiers — an HTTPS API call sidesteps
    that entirely.
    """

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        payload = {
            "from": settings.RESEND_FROM or settings.SMTP_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text

        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                API_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
        if res.status_code >= 400:
            body = (
                res.json()
                if res.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            message = body.get("message") or f"Resend send failed ({res.status_code})"
            logger.error("[email:resend] failed to=%s subject=%s: %s", to, subject, message)
            raise ResendError(message)
