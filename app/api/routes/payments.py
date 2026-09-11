from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import DbSession
from app.core.config import settings
from app.core.exceptions import AppError
from app.models.property import Property
from app.services import payment_service, paystack
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl

router = APIRouter(prefix="/payments", tags=["payments"])
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


@router.get("/config")
async def payment_config() -> dict:
    return {"publicKey": settings.PAYSTACK_PUBLIC_KEY, "currency": "NGN"}


async def _send(sender: EmailSender, to: str, rendered) -> None:
    try:
        await sender.send(to=to, subject=rendered.subject, html=rendered.html, text=rendered.text)
    except Exception:
        pass


@router.post("/webhook/paystack", include_in_schema=False)
async def paystack_webhook(
    request: Request, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> dict:
    raw = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not paystack.verify_webhook_signature(raw, signature):
        raise AppError(401, "invalid_signature", "Invalid webhook signature.")

    try:
        event = json.loads(raw)
    except ValueError:
        raise AppError(400, "invalid_payload", "Malformed webhook payload.") from None

    data = event.get("data") or {}
    reference = data.get("reference")
    if not reference:
        return {"received": True}

    payment = await payment_service.get_payment_by_reference(db, reference)
    if payment is None:
        return {"received": True}  # unknown reference: ignore, don't error (no retries)

    if event.get("event") == "charge.success":
        booking = await payment_service.mark_paid_and_settle(db, payment, data)
        await db.commit()
        if booking is not None:
            prop = await db.get(Property, booking.property_id)
            rendered = tmpl.booking_confirmed(
                guest_name=booking.guest_name,
                property_title=prop.title if prop else "your stay",
                check_in=booking.check_in,
                check_out=booking.check_out,
                total_amount=booking.total_amount,
                confirmation_code=booking.confirmation_code,
            )
            background.add_task(_send, sender, booking.guest_email, rendered)
    else:
        await payment_service.mark_failed(db, payment, data)
        await db.commit()

    return {"received": True}
