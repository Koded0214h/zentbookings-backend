from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.models.staff import AuditLog
from app.schemas.staff import (
    AdminUserListResponse,
    AdminUserOut,
    AgentInvite,
    AssignAgentRequest,
    AttendanceEdit,
    AttendanceListResponse,
    AttendanceOut,
    AttendanceSummaryResponse,
    AttendanceSummaryRow,
    AuditEntryOut,
    AuditListResponse,
    PropertyAgentsOut,
    RoleUpdate,
    StatusUpdate,
)
from app.services import attendance_service, audit, staff_service
from app.services.attendance_service import AttendanceFilters
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl
from app.services.staff_service import UserFilters

router = APIRouter(prefix="/admin", tags=["admin"])
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ---------------- users & roles ----------------
@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    role: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query(alias="isActive")] = None,
    q: Annotated[str | None, Query()] = None,
) -> AdminUserListResponse:
    rows, total, pages = await staff_service.list_users(
        db, filters=UserFilters(role=role, is_active=is_active, q=q), page=page, limit=limit
    )
    return AdminUserListResponse(
        users=[AdminUserOut.model_validate(r) for r in rows],
        total=total, page=page, limit=limit, total_pages=pages,
    )


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(user_id: str, db: DbSession, _admin: AdminUser) -> AdminUserOut:
    return AdminUserOut.model_validate(await staff_service.get_user(db, user_id))


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
async def set_role(
    user_id: str, payload: RoleUpdate, db: DbSession, admin: AdminUser, request: Request
) -> AdminUserOut:
    user = await staff_service.get_user(db, user_id)
    before = user.role
    await staff_service.set_role(db, user, payload.role)
    await audit.record(
        db, actor_id=admin.id, action="role.change", target_type="user", target_id=user_id,
        metadata={"from": before, "to": payload.role}, ip=_ip(request),
    )
    await db.commit()
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}/status", response_model=AdminUserOut)
async def set_status(
    user_id: str, payload: StatusUpdate, db: DbSession, admin: AdminUser, request: Request
) -> AdminUserOut:
    user = await staff_service.get_user(db, user_id)
    await staff_service.set_status(db, user, payload.is_active)
    await audit.record(
        db, actor_id=admin.id,
        action="user.activate" if payload.is_active else "user.deactivate",
        target_type="user", target_id=user_id, ip=_ip(request),
    )
    await db.commit()
    return AdminUserOut.model_validate(user)


@router.post("/agents/invite", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def invite_agent(
    payload: AgentInvite,
    db: DbSession,
    admin: AdminUser,
    background: BackgroundTasks,
    sender: SenderDep,
    request: Request,
) -> AdminUserOut:
    user, raw_token = await staff_service.invite_staff(
        db, first_name=payload.first_name, last_name=payload.last_name,
        email=payload.email, role=payload.role,
    )
    await audit.record(
        db, actor_id=admin.id, action="agent.invite", target_type="user", target_id=user.id,
        metadata={"role": payload.role, "email": user.email}, ip=_ip(request),
    )
    await db.commit()

    from app.core.config import settings

    url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    rendered = tmpl.staff_invite(
        first_name=user.first_name, role=payload.role, set_password_url=url
    )
    background.add_task(
        _safe_send, sender, user.email, rendered.subject, rendered.html, rendered.text
    )
    return AdminUserOut.model_validate(user)


async def _safe_send(sender, to, subject, html, text) -> None:
    try:
        await sender.send(to=to, subject=subject, html=html, text=text)
    except Exception:
        pass


# ---------------- agent assignment ----------------
@router.get("/properties/{property_id}/agents", response_model=PropertyAgentsOut)
async def list_property_agents(
    property_id: int, db: DbSession, _admin: AdminUser
) -> PropertyAgentsOut:
    return PropertyAgentsOut(
        property_id=property_id,
        agent_ids=await staff_service.property_agent_ids(db, property_id),
    )


@router.post(
    "/properties/{property_id}/agents",
    response_model=PropertyAgentsOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_property_agent(
    property_id: int, payload: AssignAgentRequest, db: DbSession, admin: AdminUser, request: Request
) -> PropertyAgentsOut:
    await staff_service.assign_agent(
        db, property_id=property_id, agent_id=payload.agent_id, by=admin.id
    )
    await audit.record(
        db, actor_id=admin.id, action="agent.assign", target_type="property",
        target_id=property_id, metadata={"agentId": payload.agent_id}, ip=_ip(request),
    )
    await db.commit()
    return PropertyAgentsOut(
        property_id=property_id,
        agent_ids=await staff_service.property_agent_ids(db, property_id),
    )


@router.delete(
    "/properties/{property_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unassign_property_agent(
    property_id: int, agent_id: str, db: DbSession, admin: AdminUser, request: Request
) -> None:
    await staff_service.unassign_agent(db, property_id=property_id, agent_id=agent_id)
    await audit.record(
        db, actor_id=admin.id, action="agent.unassign", target_type="property",
        target_id=property_id, metadata={"agentId": agent_id}, ip=_ip(request),
    )
    await db.commit()


# ---------------- attendance ----------------
@router.get("/attendance", response_model=AttendanceListResponse)
async def list_attendance(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    user_id: Annotated[str | None, Query(alias="userId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> AttendanceListResponse:
    rows, total, pages = await attendance_service.list_attendance(
        db,
        filters=AttendanceFilters(
            user_id=user_id, status=status_, date_from=date_from, date_to=date_to
        ),
        page=page, limit=limit,
    )
    return AttendanceListResponse(
        records=[AttendanceOut.model_validate(r) for r in rows],
        total=total, page=page, limit=limit, total_pages=pages,
    )


@router.get("/attendance/summary", response_model=AttendanceSummaryResponse)
async def attendance_summary(
    db: DbSession,
    _admin: AdminUser,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> AttendanceSummaryResponse:
    end = date_to or datetime.now(UTC)
    start = date_from or (end - timedelta(days=30))
    rows = await attendance_service.summary(db, date_from=start, date_to=end)
    return AttendanceSummaryResponse(
        **{"from": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        to=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        rows=[AttendanceSummaryRow(**r) for r in rows],
    )


@router.patch("/attendance/{attendance_id}", response_model=AttendanceOut)
async def edit_attendance(
    attendance_id: str, payload: AttendanceEdit, db: DbSession, admin: AdminUser, request: Request
) -> AttendanceOut:
    row = await attendance_service.edit(
        db, attendance_id,
        clock_in_at=payload.clock_in_at, clock_out_at=payload.clock_out_at, note=payload.note,
    )
    await audit.record(
        db, actor_id=admin.id, action="attendance.edit", target_type="attendance",
        target_id=attendance_id, metadata=payload.model_dump(exclude_unset=True, mode="json"),
        ip=_ip(request),
    )
    await db.commit()
    return AttendanceOut.model_validate(row)


# ---------------- audit log ----------------
@router.get("/audit", response_model=AuditListResponse)
async def list_audit(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    actor_id: Annotated[str | None, Query(alias="actorId")] = None,
    action: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query(alias="targetType")] = None,
) -> AuditListResponse:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    for col, val in (
        (AuditLog.actor_user_id, actor_id),
        (AuditLog.action, action),
        (AuditLog.target_type, target_type),
    ):
        if val:
            stmt = stmt.where(col == val)
            count_stmt = count_stmt.where(col == val)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(AuditLog.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    entries = [
        AuditEntryOut(
            id=r.id, actor_user_id=r.actor_user_id, action=r.action,
            target_type=r.target_type, target_id=r.target_id,
            metadata=r.audit_metadata, ip=r.ip, created_at=r.created_at,
        )
        for r in rows
    ]
    pages = (total + limit - 1) // limit if limit else 0
    return AuditListResponse(
        entries=entries, total=total, page=page, limit=limit, total_pages=pages
    )
