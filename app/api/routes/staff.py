from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, StaffUser
from app.schemas.staff import (
    AgentProfileOut,
    AgentProfileUpdate,
    AttendanceListResponse,
    AttendanceOut,
    AttendanceStatusOut,
    ClockInRequest,
)
from app.services import attendance_service, staff_service
from app.services.attendance_service import AttendanceFilters

router = APIRouter(prefix="/staff", tags=["staff"])


@router.post("/clock-in", response_model=AttendanceOut, status_code=status.HTTP_201_CREATED)
async def clock_in(
    payload: ClockInRequest, db: DbSession, user: StaffUser, request: Request
) -> AttendanceOut:
    row = await attendance_service.clock_in(
        db, user.id,
        source=payload.source,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return AttendanceOut.model_validate(row)


@router.post("/clock-out", response_model=AttendanceOut)
async def clock_out(db: DbSession, user: StaffUser) -> AttendanceOut:
    row = await attendance_service.clock_out(db, user.id)
    await db.commit()
    return AttendanceOut.model_validate(row)


@router.get("/me/status", response_model=AttendanceStatusOut)
async def my_status(db: DbSession, user: StaffUser) -> AttendanceStatusOut:
    return AttendanceStatusOut.model_validate(await attendance_service.status_for(db, user.id))


@router.get("/attendance/me", response_model=AttendanceListResponse)
async def my_attendance(
    db: DbSession,
    user: StaffUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AttendanceListResponse:
    rows, total, pages = await attendance_service.list_attendance(
        db, filters=AttendanceFilters(user_id=user.id), page=page, limit=limit
    )
    return AttendanceListResponse(
        records=[AttendanceOut.model_validate(r) for r in rows],
        total=total, page=page, limit=limit, total_pages=pages,
    )


@router.get("/me/profile", response_model=AgentProfileOut)
async def get_my_profile(db: DbSession, user: StaffUser) -> AgentProfileOut:
    profile = await staff_service.get_or_create_profile(db, user.id)
    await db.commit()
    return AgentProfileOut.model_validate(profile)


@router.put("/me/profile", response_model=AgentProfileOut)
async def update_my_profile(
    payload: AgentProfileUpdate, db: DbSession, user: StaffUser
) -> AgentProfileOut:
    profile = await staff_service.update_profile(
        db, user.id, payload.model_dump(exclude_unset=True)
    )
    await db.commit()
    return AgentProfileOut.model_validate(profile)
