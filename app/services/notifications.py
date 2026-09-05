from __future__ import annotations

from datetime import datetime

from app.services.email import templates as tmpl
from app.services.email.base import EmailSender

_TOUR_TEMPLATES = {
    "requested": tmpl.tour_requested,
    "confirmed": tmpl.tour_confirmed,
    "rescheduled": tmpl.tour_rescheduled,
    "cancelled": tmpl.tour_cancelled,
}


async def notify_tour(
    sender: EmailSender,
    *,
    kind: str,
    to: str,
    visitor_name: str,
    property_title: str,
    scheduled_at: datetime,
    confirmation_code: str,
) -> None:
    """Best-effort tour email. Safe to hand to BackgroundTasks (takes plain values)."""
    rendered = _TOUR_TEMPLATES[kind](
        visitor_name=visitor_name,
        property_title=property_title,
        scheduled_at=scheduled_at,
        confirmation_code=confirmation_code,
    )
    try:
        await sender.send(
            to=to, subject=rendered.subject, html=rendered.html, text=rendered.text
        )
    except Exception:  # background task: never surface to the client
        pass
