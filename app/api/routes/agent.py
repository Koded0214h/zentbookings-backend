from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, StaffUser
from app.schemas.property import PropertyOut
from app.schemas.tour import TourListResponse, TourOut
from app.services import property_service, staff_service, tour_service
from app.services.property_service import PropertyFilters
from app.services.tour_service import TourFilters

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/properties", response_model=list[PropertyOut])
async def my_properties(db: DbSession, user: StaffUser) -> list[PropertyOut]:
    ids = await staff_service.assigned_property_ids(db, user.id)
    if not ids:
        return []
    rows, _total, _pages = await property_service.list_properties(
        db, filters=PropertyFilters(), page=1, limit=100
    )
    return [PropertyOut.model_validate(r) for r in rows if r.id in set(ids)]


@router.get("/tours", response_model=TourListResponse)
async def my_tours(
    db: DbSession,
    user: StaffUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_: Annotated[str | None, Query(alias="status")] = None,
    lead_status: Annotated[str | None, Query(alias="leadStatus")] = None,
) -> TourListResponse:
    ids = await staff_service.assigned_property_ids(db, user.id)
    rows, total, pages = await tour_service.list_tours(
        db,
        filters=TourFilters(status=status_, lead_status=lead_status, property_ids=ids),
        owner=user, staff=True, page=page, limit=limit,
    )
    return TourListResponse(
        tours=[TourOut.model_validate(r) for r in rows],
        total=total, page=page, limit=limit, total_pages=pages,
    )
