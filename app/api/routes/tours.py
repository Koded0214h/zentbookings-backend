from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from app.api.deps import CurrentUser, DbSession, OptionalUser, require_roles
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.ratelimit import rate_limit
from app.models.property import Property
from app.models.tour import Tour
from app.models.user import User
from app.schemas.tour import (
    GuestTourAction,
    TourCreate,
    TourCreateResponse,
    TourListResponse,
    TourOut,
    TourPatch,
)
from app.services import audit, tour_service
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import notify_tour
from app.services.tour_service import TourFilters, TourForbidden

router = APIRouter(prefix="/tours", tags=["tours"])

SenderDep = Annotated[EmailSender, Depends(get_email_sender)]
_staff = Annotated[User, Depends(require_roles("admin", "agent"))]
_create_limit = [Depends(rate_limit("tour_create", settings.TOUR_CREATE_RATE_LIMIT))]
_lookup_limit = [Depends(rate_limit("tour_lookup", settings.TOUR_LOOKUP_RATE_LIMIT))]


def _is_staff(user: User | None) -> bool:
    return bool(user and user.role in ("admin", "agent"))


async def _title(db, property_id: int) -> str:
    prop = await db.get(Property, property_id)
    return prop.title if prop else "your property"


async def _queue_email(
    background: BackgroundTasks, sender: EmailSender, tour: Tour, title: str, kind: str
) -> None:
    background.add_task(
        notify_tour,
        sender,
        kind=kind,
        to=tour.visitor_email,
        visitor_name=tour.visitor_name,
        property_title=title,
        scheduled_at=tour.scheduled_at,
        confirmation_code=tour.confirmation_code,
    )


@router.post(
    "",
    response_model=TourCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_create_limit,
)
async def create_tour(
    payload: TourCreate,
    db: DbSession,
    background: BackgroundTasks,
    sender: SenderDep,
    user: OptionalUser,
) -> TourCreateResponse:
    tour, prop = await tour_service.create_tour(db, payload, user=user)
    await db.commit()
    await _queue_email(
        background,
        sender,
        tour,
        prop.title,
        "confirmed" if tour.status == "CONFIRMED" else "requested",
    )
    return TourCreateResponse.model_validate(tour)


@router.get("", response_model=TourListResponse)
async def list_tours(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_: Annotated[str | None, Query(alias="status")] = None,
    property_id: Annotated[int | None, Query(alias="propertyId")] = None,
) -> TourListResponse:
    staff = _is_staff(user)
    rows, total, pages = await tour_service.list_tours(
        db,
        filters=TourFilters(status=status_, property_id=property_id),
        owner=user,
        staff=staff,
        page=page,
        limit=limit,
    )
    return TourListResponse(
        tours=[TourOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
    )


@router.post("/lookup", response_model=TourOut, dependencies=_lookup_limit)
async def lookup_tour(payload: GuestTourAction, db: DbSession) -> TourOut:
    tour = await tour_service.get_tour_for_guest(
        db, code=payload.confirmation_code, email=payload.email
    )
    return TourOut.model_validate(tour)


@router.post("/cancel", response_model=TourOut, dependencies=_lookup_limit)
async def guest_cancel_tour(
    payload: GuestTourAction, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> TourOut:
    tour = await tour_service.get_tour_for_guest(
        db, code=payload.confirmation_code, email=payload.email
    )
    await tour_service.cancel_tour(db, tour)
    await db.commit()
    await _queue_email(background, sender, tour, await _title(db, tour.property_id), "cancelled")
    return TourOut.model_validate(tour)


@router.get("/{tour_id}", response_model=TourOut)
async def get_tour(tour_id: str, db: DbSession, user: CurrentUser) -> TourOut:
    tour = await tour_service.get_tour(db, tour_id)
    if not _is_staff(user) and tour.user_id != user.id:
        raise TourForbidden()
    return TourOut.model_validate(tour)


@router.delete("/{tour_id}", response_model=TourOut)
async def cancel_tour(
    tour_id: str,
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    sender: SenderDep,
    request: Request,
) -> TourOut:
    tour = await tour_service.get_tour(db, tour_id)
    if not _is_staff(user) and tour.user_id != user.id:
        raise TourForbidden()
    await tour_service.cancel_tour(db, tour)
    await audit.record(
        db, actor_id=user.id, action="tour.cancel", target_type="tour", target_id=tour_id,
        metadata={"by": "staff" if _is_staff(user) else "owner"},
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    await _queue_email(background, sender, tour, await _title(db, tour.property_id), "cancelled")
    return TourOut.model_validate(tour)


@router.post("/{tour_id}/confirm", response_model=TourOut)
async def confirm_tour(
    tour_id: str,
    db: DbSession,
    staff_user: _staff,
    background: BackgroundTasks,
    sender: SenderDep,
    request: Request,
) -> TourOut:
    tour = await tour_service.get_tour(db, tour_id)
    await tour_service.confirm_tour(db, tour)
    await audit.record(
        db, actor_id=staff_user.id, action="tour.confirm", target_type="tour",
        target_id=tour_id, ip=request.client.host if request.client else None,
    )
    await db.commit()
    await _queue_email(background, sender, tour, await _title(db, tour.property_id), "confirmed")
    return TourOut.model_validate(tour)


@router.patch("/{tour_id}", response_model=TourOut)
async def patch_tour(
    tour_id: str,
    payload: TourPatch,
    db: DbSession,
    staff_user: _staff,
    background: BackgroundTasks,
    sender: SenderDep,
    request: Request,
) -> TourOut:
    if (payload.scheduled_date is None) != (payload.scheduled_time is None):
        raise AppError(
            422, "validation_error", "scheduledDate and scheduledTime must be given together."
        )
    tour = await tour_service.get_tour(db, tour_id)
    rescheduled = payload.scheduled_date is not None
    await tour_service.patch_tour(
        db, tour,
        lead_status=payload.lead_status,
        notes=payload.notes,
        scheduled_date=payload.scheduled_date,
        scheduled_time=payload.time_obj() if rescheduled else None,
    )
    await audit.record(
        db, actor_id=staff_user.id, action="tour.update", target_type="tour",
        target_id=tour_id, metadata=payload.model_dump(exclude_unset=True, mode="json"),
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    if rescheduled:
        await _queue_email(
            background, sender, tour, await _title(db, tour.property_id), "rescheduled"
        )
    return TourOut.model_validate(tour)
