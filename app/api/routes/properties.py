from __future__ import annotations

import hashlib
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import DbSession, require_roles
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.schemas.property import (
    PropertyCreate,
    PropertyListResponse,
    PropertyOut,
    PropertyUpdate,
)
from app.schemas.tour import AvailabilityResponse, ScheduleOut, ScheduleUpdate, SlotOut
from app.services import property_service, scheduling
from app.services.property_service import PropertyFilters

router = APIRouter(prefix="/properties", tags=["properties"])

# POST/PUT/DELETE are restricted to staff.
_staff_only = [Depends(require_roles("admin", "agent"))]
_read_limit = [Depends(rate_limit("properties_read", settings.LIST_RATE_LIMIT))]

SortParam = Literal["id", "-id", "price", "-price", "newest", "oldest"]


def _cache_headers() -> dict[str, str]:
    if settings.PROPERTIES_CACHE_MAX_AGE <= 0:
        return {}
    return {"Cache-Control": f"public, max-age={settings.PROPERTIES_CACHE_MAX_AGE}"}


def _conditional(request: Request, body: str) -> Response:
    """304 if the client's If-None-Match matches, else a JSON response + ETag."""
    etag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'  # noqa: S324 - not security
    headers = {"ETag": etag, **_cache_headers()}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("", response_model=PropertyListResponse, dependencies=_read_limit)
async def list_properties(
    request: Request,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 9,
    category: Annotated[str | None, Query()] = None,
    location: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,  # noqa: A002 - matches PRD param name
    q: Annotated[str | None, Query(description="free-text over title/location/description")] = None,
    sort: SortParam = "id",
    price_min: Annotated[int | None, Query(alias="priceMin", ge=0)] = None,
    price_max: Annotated[int | None, Query(alias="priceMax", ge=0)] = None,
) -> Response:
    filters = PropertyFilters(
        category=category,
        location=location,
        type=type,
        price_min=price_min,
        price_max=price_max,
        q=q,
    )
    rows, total, total_pages = await property_service.list_properties(
        db, filters=filters, page=page, limit=limit, sort=sort
    )
    payload = PropertyListResponse(
        properties=[PropertyOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
    return _conditional(request, payload.model_dump_json(by_alias=True))


@router.get("/{property_id}", response_model=PropertyOut, dependencies=_read_limit)
async def get_property(request: Request, db: DbSession, property_id: int) -> Response:
    row = await property_service.get_property(db, property_id)
    body = PropertyOut.model_validate(row).model_dump_json(by_alias=True)
    return _conditional(request, body)


@router.get(
    "/{property_id}/availability",
    response_model=AvailabilityResponse,
    dependencies=_read_limit,
)
async def property_availability(
    property_id: int,
    db: DbSession,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    on: Annotated[date | None, Query(description="single date shortcut")] = None,
) -> AvailabilityResponse:
    await property_service.get_property(db, property_id)  # 404 if missing
    schedule = await scheduling.get_or_create_schedule(db, property_id)
    await db.commit()
    if on is not None:
        date_from = date_to = on
    slots = await scheduling.availability(
        db, schedule, from_date=date_from, to_date=date_to
    )
    return AvailabilityResponse(
        property_id=property_id,
        timezone=schedule.timezone,
        slots=[
            SlotOut(date=s.date, time=s.time, available=s.available, capacity=s.capacity)
            for s in slots
        ],
    )


@router.get(
    "/{property_id}/schedule", response_model=ScheduleOut, dependencies=_staff_only
)
async def get_schedule(property_id: int, db: DbSession) -> ScheduleOut:
    await property_service.get_property(db, property_id)
    schedule = await scheduling.get_or_create_schedule(db, property_id)
    await db.commit()
    return ScheduleOut.model_validate(schedule)


@router.put(
    "/{property_id}/schedule", response_model=ScheduleOut, dependencies=_staff_only
)
async def update_schedule(
    property_id: int, payload: ScheduleUpdate, db: DbSession
) -> ScheduleOut:
    await property_service.get_property(db, property_id)
    schedule = await scheduling.get_or_create_schedule(db, property_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)
    await db.commit()
    return ScheduleOut.model_validate(schedule)


@router.post(
    "",
    response_model=PropertyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_staff_only,
)
async def create_property(payload: PropertyCreate, db: DbSession) -> PropertyOut:
    row = await property_service.create_property(db, payload)
    await db.commit()
    return PropertyOut.model_validate(row)


@router.put("/{property_id}", response_model=PropertyOut, dependencies=_staff_only)
async def update_property(
    property_id: int, payload: PropertyUpdate, db: DbSession
) -> PropertyOut:
    row = await property_service.update_property(db, property_id, payload)
    await db.commit()
    return PropertyOut.model_validate(row)


@router.delete(
    "/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_staff_only
)
async def delete_property(property_id: int, db: DbSession) -> None:
    await property_service.delete_property(db, property_id)
    await db.commit()
