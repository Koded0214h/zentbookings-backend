from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.booking import (
    Booking,
    EscrowAllocation,
    Payment,
    PaymentAdjustment,
    PayoutRequest,
    Wallet,
)
from app.models.property import Property
from app.models.user import User


@dataclass(slots=True)
class PaymentFilters:
    status: str | None = None
    provider: str | None = None
    q: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


async def dashboard(db: AsyncSession) -> dict:
    successful_payments = int(
        await db.scalar(
            select(func.count()).select_from(Payment).where(Payment.status == "SUCCESS")
        )
        or 0
    )
    gross = int(
        await db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "SUCCESS")
        )
        or 0
    )
    split = (
        await db.execute(
            select(
                func.coalesce(func.sum(EscrowAllocation.gross_amount), 0),
                func.coalesce(func.sum(EscrowAllocation.processing_fee), 0),
                func.coalesce(func.sum(EscrowAllocation.agent_amount), 0),
                func.coalesce(func.sum(EscrowAllocation.platform_amount), 0),
            )
        )
    ).one()
    adjustments = dict(
        (
            await db.execute(
                select(PaymentAdjustment.type, func.coalesce(func.sum(PaymentAdjustment.amount), 0))
                .where(PaymentAdjustment.status == "COMPLETED")
                .group_by(PaymentAdjustment.type)
            )
        ).all()
    )
    payout_rows = dict(
        (
            await db.execute(
                select(
                    PayoutRequest.status, func.coalesce(func.sum(PayoutRequest.amount), 0)
                ).group_by(PayoutRequest.status)
            )
        ).all()
    )
    pending_payout_count = int(
        await db.scalar(
            select(func.count())
            .select_from(PayoutRequest)
            .where(PayoutRequest.status.in_(("PENDING", "APPROVED")))
        )
        or 0
    )
    monthly_rows = (
        await db.execute(
            select(EscrowAllocation.created_at, EscrowAllocation.platform_amount).order_by(
                EscrowAllocation.created_at
            )
        )
    ).all()
    buckets: dict[str, int] = {}
    for created_at, amount in monthly_rows:
        key = created_at.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + amount

    return {
        "gross_collections": gross,
        "booking_revenue": int(split[0]) - int(split[1]),
        "processing_fees": int(split[1]),
        "agent_share": int(split[2]),
        "platform_revenue": int(split[3]),
        "refunded_amount": int(adjustments.get("REFUND", 0)),
        "chargeback_amount": int(adjustments.get("CHARGEBACK", 0)),
        "wallet_liability": int(
            await db.scalar(select(func.coalesce(func.sum(Wallet.balance), 0))) or 0
        ),
        "pending_payout_amount": int(payout_rows.get("PENDING", 0))
        + int(payout_rows.get("APPROVED", 0)),
        "pending_payout_count": pending_payout_count,
        "completed_payout_amount": int(payout_rows.get("DISBURSED", 0)),
        "successful_payments": successful_payments,
        "active_bookings": int(
            await db.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.status.in_(("CONFIRMED", "ACTIVE")))
            )
            or 0
        ),
        "total_users": int(await db.scalar(select(func.count()).select_from(User)) or 0),
        "active_listings": int(
            await db.scalar(
                select(func.count()).select_from(Property).where(Property.deleted_at.is_(None))
            )
            or 0
        ),
        "monthly_revenue": [{"month": k, "amount": v} for k, v in sorted(buckets.items())[-12:]],
    }


def _payment_query(filters: PaymentFilters):
    stmt = select(Payment, Booking.guest_email, Booking.property_id).join(
        Booking, Booking.id == Payment.booking_id
    )
    if filters.status:
        stmt = stmt.where(Payment.status == filters.status.upper())
    if filters.provider:
        stmt = stmt.where(Payment.provider == filters.provider.lower())
    if filters.q:
        term = f"%{filters.q.strip()}%"
        stmt = stmt.where(or_(Payment.reference.ilike(term), Booking.guest_email.ilike(term)))
    if filters.date_from:
        stmt = stmt.where(Payment.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Payment.created_at <= filters.date_to)
    return stmt


async def list_payments(
    db: AsyncSession, *, filters: PaymentFilters, page: int, limit: int
) -> tuple[list[tuple], int, int]:
    query = _payment_query(filters)
    count_query = select(func.count()).select_from(query.subquery())
    total = int(await db.scalar(count_query) or 0)
    rows = (
        await db.execute(
            query.order_by(Payment.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
    ).all()
    return list(rows), total, ceil(total / limit) if limit else 0


async def get_payment(db: AsyncSession, payment_id: str) -> tuple[Payment, str, int]:
    row = (
        await db.execute(
            select(Payment, Booking.guest_email, Booking.property_id)
            .join(Booking, Booking.id == Payment.booking_id)
            .where(Payment.id == payment_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "payment_not_found", "Payment not found.")
    return row


async def adjustments(db: AsyncSession, payment_id: str) -> list[PaymentAdjustment]:
    return list(
        (
            await db.scalars(
                select(PaymentAdjustment)
                .where(PaymentAdjustment.payment_id == payment_id)
                .order_by(PaymentAdjustment.created_at.desc())
            )
        ).all()
    )


async def create_adjustment(
    db: AsyncSession,
    *,
    payment: Payment,
    adjustment_type: str,
    amount: int,
    reason: str,
    status: str,
    provider_reference: str | None,
    admin_id: str,
) -> PaymentAdjustment:
    if payment.status != "SUCCESS":
        raise AppError(409, "payment_state", "Only successful payments can be adjusted.")
    existing = int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentAdjustment.amount), 0)).where(
                PaymentAdjustment.payment_id == payment.id,
                PaymentAdjustment.status.in_(("PENDING", "COMPLETED")),
            )
        )
        or 0
    )
    if existing + amount > payment.amount:
        raise AppError(
            409, "adjustment_exceeds_payment", "Adjustments cannot exceed the payment amount."
        )
    now = datetime.now(UTC)
    row = PaymentAdjustment(
        payment_id=payment.id,
        type=adjustment_type,
        amount=amount,
        currency=payment.currency,
        status=status,
        reason=reason,
        provider_reference=provider_reference,
        created_by=admin_id,
        completed_at=now if status == "COMPLETED" else None,
    )
    db.add(row)
    await db.flush()
    return row


async def update_adjustment(
    db: AsyncSession, adjustment_id: str, *, status: str, provider_reference: str | None
) -> PaymentAdjustment:
    row = await db.get(PaymentAdjustment, adjustment_id)
    if row is None:
        raise AppError(404, "adjustment_not_found", "Payment adjustment not found.")
    if row.status in ("COMPLETED", "CANCELLED") and row.status != status:
        raise AppError(409, "adjustment_state", "A completed or cancelled adjustment is final.")
    row.status = status
    if provider_reference is not None:
        row.provider_reference = provider_reference
    row.completed_at = datetime.now(UTC) if status == "COMPLETED" else None
    await db.flush()
    return row
