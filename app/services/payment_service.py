from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.booking import Booking, EscrowAllocation, Payment
from app.models.staff import PropertyAgent
from app.models.user import User
from app.services import wallet_service
from app.services.payment_providers import get_payment_provider


class PaymentNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "payment_not_found", "Payment not found.")


async def initiate_payment(db: AsyncSession, booking: Booking, *, redirect_url: str) -> dict:
    reference = f"{booking.id}-{booking.confirmation_code}".lower()
    provider = get_payment_provider()
    result = await provider.initialize_payment(
        email=booking.guest_email,
        name=booking.guest_name,
        phone=booking.guest_phone,
        amount_naira=booking.total_amount,
        reference=reference,
        callback_url=redirect_url,
        metadata={"booking_id": booking.id, "property_id": booking.property_id},
    )
    db.add(
        Payment(
            booking_id=booking.id,
            provider=provider.name,
            reference=result["reference"],
            amount=booking.total_amount,
            currency=booking.currency,
        )
    )
    await db.flush()
    return {"authorization_url": result["authorization_url"], "reference": result["reference"]}


async def get_payment_by_reference(db: AsyncSession, reference: str) -> Payment | None:
    return await db.scalar(select(Payment).where(Payment.reference == reference))


async def mark_paid_and_settle(db: AsyncSession, payment: Payment, event_data: dict) -> Booking:
    """Idempotent: safe to call more than once for the same payment."""
    booking = await db.get(Booking, payment.booking_id)
    if payment.status == "SUCCESS":
        return booking

    payment.status = "SUCCESS"
    payment.raw_payload = event_data

    if booking is not None and booking.status == "PENDING_PAYMENT":
        booking.status = "CONFIRMED"

        from app.models.property import Property

        prop = await db.get(Property, booking.property_id)
        agent_id = await db.scalar(
            select(PropertyAgent.agent_id)
            .join(User, User.id == PropertyAgent.agent_id)
            .where(
                PropertyAgent.property_id == booking.property_id,
                User.role == "agent",
                User.is_active.is_(True),
            )
            .order_by(PropertyAgent.created_at.asc(), PropertyAgent.agent_id.asc())
            .limit(1)
        )
        if agent_id is None and prop is not None and prop.created_by_id:
            creator = await db.get(User, prop.created_by_id)
            if creator is not None and creator.role in ("agent", "admin") and creator.is_active:
                agent_id = creator.id

        if agent_id is not None:
            percent = settings.AGENT_REVENUE_PERCENT
            revenue_base = booking.total_amount - booking.processing_fee
            agent_amount = round(revenue_base * percent / 100)
            platform_amount = booking.total_amount - agent_amount
            db.add(
                EscrowAllocation(
                    payment_id=payment.id,
                    booking_id=booking.id,
                    agent_id=agent_id,
                    gross_amount=booking.total_amount,
                    processing_fee=booking.processing_fee,
                    agent_amount=agent_amount,
                    platform_amount=platform_amount,
                    agent_percent=percent,
                    currency=booking.currency,
                )
            )
            await wallet_service.credit(
                db,
                agent_id,
                agent_amount,
                booking_id=booking.id,
                note=(
                    f"Booking {booking.confirmation_code}: {percent}% agent share "
                    f"of {revenue_base}; processing fee excluded"
                ),
            )

    await db.flush()
    return booking


def validate_settlement(payment: Payment, event_data: dict) -> None:
    """Never fulfil a booking if the provider reports a different amount/currency."""
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(str(event_data.get("amount")))
    except (InvalidOperation, TypeError):
        raise AppError(
            400, "invalid_payment_amount", "Payment amount is missing or invalid."
        ) from None
    if amount != Decimal(payment.amount) or event_data.get("currency") != payment.currency:
        raise AppError(409, "payment_amount_mismatch", "Payment amount or currency does not match.")


async def mark_failed(db: AsyncSession, payment: Payment, event_data: dict) -> None:
    if payment.status == "SUCCESS":
        return
    payment.status = "FAILED"
    payment.raw_payload = event_data
    await db.flush()
