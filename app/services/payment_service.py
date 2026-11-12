from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.booking import Booking, EscrowAllocation, Payment
from app.models.staff import PropertyAgent
from app.models.user import User
from app.services import paystack, wallet_service


class PaymentNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "payment_not_found", "Payment not found.")


async def initiate_payment(db: AsyncSession, booking: Booking, *, redirect_url: str) -> dict:
    reference = f"{booking.id}-{booking.confirmation_code}".lower()
    result = await paystack.initialize_transaction(
        email=booking.guest_email,
        amount_naira=booking.total_amount,
        reference=reference,
        callback_url=redirect_url,
        metadata={"booking_id": booking.id, "property_id": booking.property_id},
    )
    db.add(
        Payment(
            booking_id=booking.id,
            provider="paystack",
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
            agent_amount = round(booking.total_amount * percent / 100)
            platform_amount = booking.total_amount - agent_amount
            db.add(
                EscrowAllocation(
                    payment_id=payment.id,
                    booking_id=booking.id,
                    agent_id=agent_id,
                    gross_amount=booking.total_amount,
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
                    f"of {booking.total_amount}"
                ),
            )

    await db.flush()
    return booking


async def mark_failed(db: AsyncSession, payment: Payment, event_data: dict) -> None:
    if payment.status == "SUCCESS":
        return
    payment.status = "FAILED"
    payment.raw_payload = event_data
    await db.flush()
