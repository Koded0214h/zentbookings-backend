from __future__ import annotations

import secrets
from dataclasses import dataclass
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.property import Property
from app.models.tour import Tour
from app.models.user import User
from app.schemas.tour import TourCreate
from app.services import scheduling

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


class TourNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "tour_not_found", "Tour not found.")


class TourForbidden(AppError):
    def __init__(self) -> None:
        super().__init__(403, "forbidden", "You cannot modify this booking.")


class TourStateError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "tour_state", message)


@dataclass(slots=True)
class TourFilters:
    status: str | None = None
    property_id: int | None = None


async def _unique_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = "ZENT-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not await db.scalar(select(Tour.id).where(Tour.confirmation_code == code)):
            return code
    raise AppError(500, "code_generation", "Could not allocate a confirmation code.")


async def create_tour(
    db: AsyncSession, data: TourCreate, *, user: User | None
) -> tuple[Tour, Property]:
    prop = await db.get(Property, data.property_id)
    if prop is None:
        raise AppError(404, "property_not_found", "Property not found.")

    # Resolve visitor identity: explicit fields win, else fall back to the account.
    name = data.visitor_name or (user.full_name if user else None)
    email = data.visitor_email or (user.email if user else None)
    phone = data.visitor_phone
    missing = [
        f
        for f, v in (("visitorName", name), ("visitorEmail", email), ("visitorPhone", phone))
        if not v
    ]
    if missing:
        raise AppError(
            422, "validation_error", f"Missing required visitor fields: {', '.join(missing)}"
        )

    schedule = await scheduling.get_or_create_schedule(db, prop.id)
    scheduled_at = await scheduling.resolve_and_validate_slot(
        db, schedule, d=data.scheduled_date, t=data.time_obj()
    )

    status = "CONFIRMED" if schedule.auto_confirm else "PENDING"
    tour = Tour(
        property_id=prop.id,
        user_id=user.id if user else None,
        visitor_name=name,
        visitor_email=str(email).lower(),
        visitor_phone=phone,
        scheduled_at=scheduled_at,
        notes=data.notes,
        status=status,
        confirmation_code=await _unique_code(db),
    )
    db.add(tour)
    await db.flush()
    return tour, prop


async def get_tour(db: AsyncSession, tour_id: str) -> Tour:
    tour = await db.get(Tour, tour_id)
    if tour is None:
        raise TourNotFound()
    return tour


async def get_tour_for_guest(db: AsyncSession, *, code: str, email: str) -> Tour:
    tour = await db.scalar(
        select(Tour).where(
            Tour.confirmation_code == code.strip().upper(),
            func.lower(Tour.visitor_email) == email.strip().lower(),
        )
    )
    if tour is None:
        raise TourNotFound()
    return tour


async def list_tours(
    db: AsyncSession,
    *,
    filters: TourFilters,
    owner: User | None,
    staff: bool,
    page: int,
    limit: int,
) -> tuple[list[Tour], int, int]:
    stmt = select(Tour)
    count_stmt = select(func.count()).select_from(Tour)
    if not staff:
        # a signed-in non-staff user sees only their own
        uid = owner.id if owner else "\x00none"
        stmt = stmt.where(Tour.user_id == uid)
        count_stmt = count_stmt.where(Tour.user_id == uid)
    if filters.status:
        stmt = stmt.where(Tour.status == filters.status.upper())
        count_stmt = count_stmt.where(Tour.status == filters.status.upper())
    if filters.property_id is not None:
        stmt = stmt.where(Tour.property_id == filters.property_id)
        count_stmt = count_stmt.where(Tour.property_id == filters.property_id)

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(Tour.scheduled_at.desc()).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0


async def confirm_tour(db: AsyncSession, tour: Tour) -> Tour:
    if tour.status == "CONFIRMED":
        return tour
    if tour.status == "CANCELLED":
        raise TourStateError("A cancelled tour cannot be confirmed.")
    tour.status = "CONFIRMED"
    await db.flush()
    return tour


async def cancel_tour(db: AsyncSession, tour: Tour) -> Tour:
    if tour.status == "CANCELLED":
        return tour
    tour.status = "CANCELLED"
    await db.flush()
    return tour
