from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import DbSession
from app.core.config import settings
from app.models.property import Property
from app.services import payment_service, wallet_service
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl
from app.services.payment_providers import get_payment_provider

router = APIRouter(prefix="/payments", tags=["payments"])
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


@router.get("/config")
async def payment_config() -> dict:
    return {"provider": settings.PAYMENT_PROVIDER, "currency": "NGN"}


async def _send(sender: EmailSender, to: str, rendered) -> None:
    try:
        await sender.send(to=to, subject=rendered.subject, html=rendered.html, text=rendered.text)
    except Exception:
        pass


@router.post("/webhook/bachs", include_in_schema=False)
async def bachs_webhook(
    request: Request, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> dict:
    raw = await request.body()
    event = get_payment_provider().parse_webhook(raw, request.headers)
    data = event.data
    reference = event.reference
    if not reference:
        return {"received": True}

    if event.kind in ("payout_success", "payout_failed"):
        await wallet_service.process_transfer_event(
            db,
            reference=reference,
            succeeded=event.kind == "payout_success",
        )
        await db.commit()
        return {"received": True}

    payment = await payment_service.get_payment_by_reference(db, reference)
    if payment is None:
        return {"received": True}  # unknown reference: ignore, don't error (no retries)

    if event.kind == "payment_success":
        payment_service.validate_settlement(payment, data)
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
    elif event.kind == "payment_failed":
        await payment_service.mark_failed(db, payment, data)
        await db.commit()

    return {"received": True}
