from __future__ import annotations

import logging

from app.services.email.base import EmailSender

logger = logging.getLogger("zent.email")


class ConsoleEmailSender(EmailSender):
    """Non-production sender: logs the message instead of delivering it."""

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        logger.info(
            "[email:console] to=%s subject=%s\n%s",
            to,
            subject,
            text or html,
        )
