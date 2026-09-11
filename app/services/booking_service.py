from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.booking import ACTIVE_BOOKING_STATUSES, Booking
from app.models.property import Property
from app.models.user import User
from app.schemas.booking import BookingCreate

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


class BookingNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "booking_not_found", "Booking not found.")


class BookingForbidden(AppError):
    def __init__(self) -> None:
        super().__init__(403, "forbidden", "You cannot access this booking.")


class DatesUnavailable(AppError):
    def __init__(self, message: str = "Those dates are not available.") -> None:
        super().__init__(409, "dates_unavailable", message)


class BookingStateError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "booking_state", message)


@dataclass(slots=True)
class BookingFilters:
    status: str | None = None
    property_id: int | None = None
    property_ids: list[int] | None = None


async def _unique_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = "ZBK-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not await db.scalar(select(Booking.id).where(Booking.confirmation_code == code)):
            return code
    raise AppError(500, "code_generation", "Could not allocate a confirmation code.")


async def _has_overlap(
    db: AsyncSession, property_id: int, check_in: date, check_out: date
) -> bool:
    # standard interval overlap: existing.check_in < new.check_out AND
    # existing.check_out > new.check_in
    stmt = select(Booking.id).where(
        Booking.property_id == property_id,
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        Booking.check_in < check_out,
        Booking.check_out > check_in,
    )
    return (await db.scalar(stmt)) is not None


async def create_booking(
    db: AsyncSession, data: BookingCreate, *, user: User | None
) -> tuple[Booking, Property]:
    prop = await db.get(Property, data.property_id)
    if prop is None or prop.deleted_at is not None:
        raise AppError(404, "property_not_found", "Property not found.")

    name = data.guest_name or (user.full_name if user else None)
    email = data.guest_email or (user.email if user else None)
    phone = data.guest_phone
    missing = [
        f for f, v in (("guestName", name), ("guestEmail", email), ("guestPhone", phone)) if not v
    ]
    if missing:
        raise AppError(
            422, "validation_error", f"Missing required guest fields: {', '.join(missing)}"
        )

    if data.check_out <= data.check_in:
        raise AppError(422, "validation_error", "checkOut must be after checkIn.")
    if data.check_in < date.today():
        raise DatesUnavailable("checkIn cannot be in the past.")

    nights = (data.check_out - data.check_in).days
    if nights < prop.minimum_stay_nights:
        raise DatesUnavailable(
            f"This listing requires a minimum stay of {prop.minimum_stay_nights} night(s)."
        )
    if data.guests > prop.max_guests:
        raise AppError(
            422, "validation_error", f"This listing allows at most {prop.max_guests} guest(s)."
        )

    if await _has_overlap(db, prop.id, data.check_in, data.check_out):
        raise DatesUnavailable()

    subtotal = prop.price * nights
    total = subtotal + prop.cleaning_fee + prop.security_deposit

    booking = Booking(
        property_id=prop.id,
        user_id=user.id if user else None,
        guest_name=name,
        guest_email=str(email).lower(),
        guest_phone=phone,
        check_in=data.check_in,
        check_out=data.check_out,
        nights=nights,
        guests=data.guests,
        price_per_night=prop.price,
        cleaning_fee=prop.cleaning_fee,
        security_deposit=prop.security_deposit,
        subtotal=subtotal,
        total_amount=total,
        currency="NGN",
        status="PENDING_PAYMENT",
        notes=data.notes,
        confirmation_code=await _unique_code(db),
    )
    db.add(booking)
    await db.flush()
    return booking, prop


async def get_booking(db: AsyncSession, booking_id: str) -> Booking:
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise BookingNotFound()
    return booking


async def get_booking_for_guest(db: AsyncSession, *, code: str, email: str) -> Booking:
    booking = await db.scalar(
        select(Booking).where(
            Booking.confirmation_code == code.strip().upper(),
            func.lower(Booking.guest_email) == email.strip().lower(),
        )
    )
    if booking is None:
        raise BookingNotFound()
    return booking


async def list_bookings(
    db: AsyncSession,
    *,
    filters: BookingFilters,
    owner: User | None,
    staff: bool,
    page: int,
    limit: int,
) -> tuple[list[Booking], int, int]:
    stmt = select(Booking)
    count_stmt = select(func.count()).select_from(Booking)
    if not staff:
        uid = owner.id if owner else "\x00none"
        stmt = stmt.where(Booking.user_id == uid)
        count_stmt = count_stmt.where(Booking.user_id == uid)
    if filters.status:
        stmt = stmt.where(Booking.status == filters.status.upper())
        count_stmt = count_stmt.where(Booking.status == filters.status.upper())
    if filters.property_id is not None:
        stmt = stmt.where(Booking.property_id == filters.property_id)
        count_stmt = count_stmt.where(Booking.property_id == filters.property_id)
    if filters.property_ids is not None:
        stmt = stmt.where(Booking.property_id.in_(filters.property_ids or [-1]))
        count_stmt = count_stmt.where(Booking.property_id.in_(filters.property_ids or [-1]))

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(Booking.created_at.desc()).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0


async def cancel_booking(db: AsyncSession, booking: Booking) -> Booking:
    if booking.status == "CANCELLED":
        return booking
    if booking.status == "COMPLETED":
        raise BookingStateError("A completed booking cannot be cancelled.")
    booking.status = "CANCELLED"
    await db.flush()
    return booking


async def expire_unpaid(db: AsyncSession, *, older_than_minutes: int) -> int:
    from datetime import UTC, datetime

    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    rows = (
        (
            await db.execute(
                select(Booking).where(
                    Booking.status == "PENDING_PAYMENT", Booking.created_at < cutoff
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "CANCELLED"
    if rows:
        await db.flush()
    return len(rows)


async def blocked_ranges(
    db: AsyncSession, property_id: int, *, from_date: date, to_date: date
) -> list[tuple[date, date]]:
    rows = (
        await db.execute(
            select(Booking.check_in, Booking.check_out).where(
                Booking.property_id == property_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.check_in < to_date,
                Booking.check_out > from_date,
            )
        )
    ).all()
    return [(r[0], r[1]) for r in rows]
