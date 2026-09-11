from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from app.api.deps import CurrentUser, DbSession, OptionalUser, require_roles
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.models.booking import Booking
from app.models.property import Property
from app.models.user import User
from app.schemas.booking import (
    BookingCreate,
    BookingCreateResponse,
    BookingListResponse,
    BookingOut,
    GuestBookingAction,
    PaymentInit,
)
from app.services import audit, booking_service, oauth, payment_service
from app.services.booking_service import BookingFilters, BookingForbidden
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl

router = APIRouter(prefix="/bookings", tags=["bookings"])

SenderDep = Annotated[EmailSender, Depends(get_email_sender)]
_staff = Annotated[User, Depends(require_roles("admin", "agent"))]
_create_limit = [Depends(rate_limit("booking_create", settings.BOOKING_CREATE_RATE_LIMIT))]
_lookup_limit = [Depends(rate_limit("booking_lookup", settings.BOOKING_LOOKUP_RATE_LIMIT))]


def _is_staff(user: User | None) -> bool:
    return bool(user and user.role in ("admin", "agent"))


async def _send(sender: EmailSender, to: str, rendered) -> None:
    try:
        await sender.send(to=to, subject=rendered.subject, html=rendered.html, text=rendered.text)
    except Exception:
        pass


async def _title(db, property_id: int) -> str:
    prop = await db.get(Property, property_id)
    return prop.title if prop else "your stay"


async def _queue_cancel_email(
    background: BackgroundTasks, sender: EmailSender, db, booking: Booking
) -> None:
    rendered = tmpl.booking_cancelled(
        guest_name=booking.guest_name,
        property_title=await _title(db, booking.property_id),
        check_in=booking.check_in,
        check_out=booking.check_out,
        confirmation_code=booking.confirmation_code,
    )
    background.add_task(_send, sender, booking.guest_email, rendered)


@router.post(
    "",
    response_model=BookingCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_create_limit,
)
async def create_booking(
    payload: BookingCreate, db: DbSession, user: OptionalUser
) -> BookingCreateResponse:
    booking, _prop = await booking_service.create_booking(db, payload, user=user)
    await db.commit()

    redirect_target = oauth.validate_frontend_redirect(
        payload.redirect_url or f"{settings.FRONTEND_BASE_URL}/"
    )
    payment = await payment_service.initiate_payment(db, booking, redirect_url=redirect_target)
    await db.commit()

    return BookingCreateResponse(
        booking=BookingOut.model_validate(booking),
        payment=PaymentInit(
            authorization_url=payment["authorization_url"], reference=payment["reference"]
        ),
    )


@router.get("", response_model=BookingListResponse)
async def list_bookings(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_: Annotated[str | None, Query(alias="status")] = None,
    property_id: Annotated[int | None, Query(alias="propertyId")] = None,
) -> BookingListResponse:
    rows, total, pages = await booking_service.list_bookings(
        db,
        filters=BookingFilters(status=status_, property_id=property_id),
        owner=user,
        staff=_is_staff(user),
        page=page,
        limit=limit,
    )
    return BookingListResponse(
        bookings=[BookingOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
    )


@router.post("/lookup", response_model=BookingOut, dependencies=_lookup_limit)
async def lookup_booking(payload: GuestBookingAction, db: DbSession) -> BookingOut:
    booking = await booking_service.get_booking_for_guest(
        db, code=payload.confirmation_code, email=payload.email
    )
    return BookingOut.model_validate(booking)


@router.post("/cancel", response_model=BookingOut, dependencies=_lookup_limit)
async def guest_cancel_booking(
    payload: GuestBookingAction, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> BookingOut:
    booking = await booking_service.get_booking_for_guest(
        db, code=payload.confirmation_code, email=payload.email
    )
    await booking_service.cancel_booking(db, booking)
    await db.commit()
    await _queue_cancel_email(background, sender, db, booking)
    return BookingOut.model_validate(booking)


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: str, db: DbSession, user: CurrentUser) -> BookingOut:
    booking = await booking_service.get_booking(db, booking_id)
    if not _is_staff(user) and booking.user_id != user.id:
        raise BookingForbidden()
    return BookingOut.model_validate(booking)


@router.delete("/{booking_id}", response_model=BookingOut)
async def cancel_booking(
    booking_id: str,
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    sender: SenderDep,
    request: Request,
) -> BookingOut:
    booking = await booking_service.get_booking(db, booking_id)
    if not _is_staff(user) and booking.user_id != user.id:
        raise BookingForbidden()
    await booking_service.cancel_booking(db, booking)
    await audit.record(
        db,
        actor_id=user.id,
        action="booking.cancel",
        target_type="booking",
        target_id=booking_id,
        metadata={"by": "staff" if _is_staff(user) else "owner"},
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    await _queue_cancel_email(background, sender, db, booking)
    return BookingOut.model_validate(booking)
