from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.exceptions import AppError
from app.models.booking import Booking, EscrowAllocation, Payment, PayoutRequest, Wallet
from app.models.staff import AuditLog
from app.schemas.booking import BookingOut
from app.schemas.staff import (
    AdminBookingUpdate,
    AdminDashboardOut,
    AdminEscrowListResponse,
    AdminPaymentDetailOut,
    AdminPaymentListResponse,
    AdminPaymentOut,
    AdminPayoutListResponse,
    AdminUserListResponse,
    AdminUserOut,
    AdminWalletListResponse,
    AdminWalletOut,
    AgentInvite,
    AgentProfileOut,
    AgentProfileUpdate,
    AssignAgentRequest,
    AttendanceEdit,
    AttendanceListResponse,
    AttendanceOut,
    AttendanceSummaryResponse,
    AttendanceSummaryRow,
    AuditEntryOut,
    AuditListResponse,
    EscrowAllocationOut,
    PaymentAdjustmentCreate,
    PaymentAdjustmentOut,
    PaymentAdjustmentUpdate,
    PayoutOut,
    PayoutReview,
    PlatformConfigOut,
    PropertyAgentsOut,
    RoleUpdate,
    StatusUpdate,
)
from app.services import (
    admin_finance_service,
    attendance_service,
    audit,
    staff_service,
    wallet_service,
)
from app.services.admin_finance_service import PaymentFilters
from app.services.attendance_service import AttendanceFilters
from app.services.booking_service import BookingStateError
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl
from app.services.staff_service import UserFilters

router = APIRouter(prefix="/admin", tags=["admin"])
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _payment_out(row: tuple) -> AdminPaymentOut:
    payment, guest_email, property_id = row
    return AdminPaymentOut.model_validate(
        {
            **payment.__dict__,
            "guest_email": guest_email,
            "property_id": property_id,
        }
    )


@router.get("/dashboard", response_model=AdminDashboardOut)
async def admin_dashboard(db: DbSession, _admin: AdminUser) -> AdminDashboardOut:
    return AdminDashboardOut.model_validate(await admin_finance_service.dashboard(db))


@router.get("/config", response_model=PlatformConfigOut)
async def platform_config(_admin: AdminUser) -> PlatformConfigOut:
    return PlatformConfigOut(
        currency="NGN",
        payment_provider=settings.PAYMENT_PROVIDER,
        agent_revenue_percent=settings.AGENT_REVENUE_PERCENT,
        platform_revenue_percent=100 - settings.AGENT_REVENUE_PERCENT,
        processing_fee_percent=settings.PROCESSING_FEE_PERCENT,
        payment_timeout_minutes=settings.BOOKING_PAYMENT_TIMEOUT_MINUTES,
        bachs_configured=settings.bachs_configured,
        ninja_configured=settings.ninja_configured,
        smtp_configured=bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD),
        cloudinary_configured=settings.cloudinary_configured,
    )


@router.get("/payments", response_model=AdminPaymentListResponse)
async def list_payments(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_: Annotated[str | None, Query(alias="status")] = None,
    provider: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> AdminPaymentListResponse:
    rows, total, pages = await admin_finance_service.list_payments(
        db,
        filters=PaymentFilters(
            status=status_, provider=provider, q=q, date_from=date_from, date_to=date_to
        ),
        page=page,
        limit=limit,
    )
    return AdminPaymentListResponse(
        payments=[_payment_out(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
    )


@router.get("/payments/{payment_id}", response_model=AdminPaymentDetailOut)
async def get_payment(payment_id: str, db: DbSession, _admin: AdminUser) -> AdminPaymentDetailOut:
    row = await admin_finance_service.get_payment(db, payment_id)
    base = _payment_out(row).model_dump()
    base["adjustments"] = [
        PaymentAdjustmentOut.model_validate(r)
        for r in await admin_finance_service.adjustments(db, payment_id)
    ]
    return AdminPaymentDetailOut.model_validate(base)


@router.post(
    "/payments/{payment_id}/adjustments",
    response_model=PaymentAdjustmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_adjustment(
    payment_id: str,
    payload: PaymentAdjustmentCreate,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> PaymentAdjustmentOut:
    payment, _email, _property_id = await admin_finance_service.get_payment(db, payment_id)
    row = await admin_finance_service.create_adjustment(
        db,
        payment=payment,
        adjustment_type=payload.type,
        amount=payload.amount,
        reason=payload.reason,
        status=payload.status,
        provider_reference=payload.provider_reference,
        admin_id=admin.id,
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action=f"payment.{payload.type.lower()}",
        target_type="payment",
        target_id=payment_id,
        metadata={"adjustmentId": row.id, "amount": row.amount, "status": row.status},
        ip=_ip(request),
    )
    await db.commit()
    return PaymentAdjustmentOut.model_validate(row)


@router.patch("/payment-adjustments/{adjustment_id}", response_model=PaymentAdjustmentOut)
async def update_payment_adjustment(
    adjustment_id: str,
    payload: PaymentAdjustmentUpdate,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> PaymentAdjustmentOut:
    row = await admin_finance_service.update_adjustment(
        db, adjustment_id, status=payload.status, provider_reference=payload.provider_reference
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action="payment.adjustment_update",
        target_type="payment_adjustment",
        target_id=row.id,
        metadata={"status": row.status},
        ip=_ip(request),
    )
    await db.commit()
    return PaymentAdjustmentOut.model_validate(row)


# ---------------- escrow, wallets & payout approvals ----------------
@router.get("/wallets", response_model=list[AdminWalletOut])
async def list_wallets(db: DbSession, _admin: AdminUser) -> list[AdminWalletOut]:
    rows = await db.scalars(select(Wallet).order_by(Wallet.updated_at.desc()))
    return [AdminWalletOut.model_validate(row) for row in rows.all()]


@router.get("/escrow", response_model=list[EscrowAllocationOut])
async def list_escrow(db: DbSession, _admin: AdminUser) -> list[EscrowAllocationOut]:
    rows = await db.scalars(select(EscrowAllocation).order_by(EscrowAllocation.created_at.desc()))
    return [EscrowAllocationOut.model_validate(row) for row in rows.all()]


@router.get("/payouts", response_model=list[PayoutOut])
async def list_payout_requests(
    db: DbSession,
    _admin: AdminUser,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[PayoutOut]:
    rows = await wallet_service.list_payouts(db, status=status_)
    return [PayoutOut.model_validate(row) for row in rows]


@router.get("/finance/wallets", response_model=AdminWalletListResponse)
async def paginated_wallets(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    currency: Annotated[str | None, Query()] = None,
    min_balance: Annotated[int | None, Query(alias="minBalance", ge=0)] = None,
) -> AdminWalletListResponse:
    stmt = select(Wallet)
    count_stmt = select(func.count()).select_from(Wallet)
    if currency:
        stmt = stmt.where(Wallet.currency == currency.upper())
        count_stmt = count_stmt.where(Wallet.currency == currency.upper())
    if min_balance is not None:
        stmt = stmt.where(Wallet.balance >= min_balance)
        count_stmt = count_stmt.where(Wallet.balance >= min_balance)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.scalars(
            stmt.order_by(Wallet.updated_at.desc()).offset((page - 1) * limit).limit(limit)
        )
    ).all()
    return AdminWalletListResponse(
        wallets=[AdminWalletOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


@router.get("/finance/escrow", response_model=AdminEscrowListResponse)
async def paginated_escrow(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    agent_id: Annotated[str | None, Query(alias="agentId")] = None,
    booking_id: Annotated[str | None, Query(alias="bookingId")] = None,
) -> AdminEscrowListResponse:
    stmt = select(EscrowAllocation)
    count_stmt = select(func.count()).select_from(EscrowAllocation)
    for column, value in (
        (EscrowAllocation.agent_id, agent_id),
        (EscrowAllocation.booking_id, booking_id),
    ):
        if value:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.scalars(
            stmt.order_by(EscrowAllocation.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).all()
    return AdminEscrowListResponse(
        allocations=[EscrowAllocationOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


@router.get("/finance/payouts", response_model=AdminPayoutListResponse)
async def paginated_payouts(
    db: DbSession,
    _admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_: Annotated[str | None, Query(alias="status")] = None,
    agent_id: Annotated[str | None, Query(alias="agentId")] = None,
) -> AdminPayoutListResponse:
    stmt = select(PayoutRequest)
    count_stmt = select(func.count()).select_from(PayoutRequest)
    if status_:
        stmt = stmt.where(PayoutRequest.status == status_.upper())
        count_stmt = count_stmt.where(PayoutRequest.status == status_.upper())
    if agent_id:
        stmt = stmt.where(PayoutRequest.agent_id == agent_id)
        count_stmt = count_stmt.where(PayoutRequest.agent_id == agent_id)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.scalars(
            stmt.order_by(PayoutRequest.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
    ).all()
    return AdminPayoutListResponse(
        payouts=[PayoutOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


@router.patch("/payouts/{payout_id}", response_model=PayoutOut)
async def review_payout_request(
    payout_id: str,
    payload: PayoutReview,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> PayoutOut:
    row = await wallet_service.review_payout(
        db,
        payout_id,
        admin_id=admin.id,
        approve=payload.decision == "approve",
        note=payload.note,
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action=f"payout.{row.status.lower()}",
        target_type="payout",
        target_id=row.id,
        metadata={"amount": row.amount, "agentId": row.agent_id},
        ip=_ip(request),
    )
    await db.commit()
    return PayoutOut.model_validate(row)


# ---------------- booking administration ----------------
@router.patch("/bookings/{booking_id}", response_model=BookingOut)
async def update_booking(
    booking_id: str,
    payload: AdminBookingUpdate,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> BookingOut:
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise AppError(404, "booking_not_found", "Booking not found.")
    before = booking.status
    if payload.status is not None and payload.status != booking.status:
        allowed = {
            "CONFIRMED": {"ACTIVE", "CANCELLED"},
            "ACTIVE": {"COMPLETED", "CANCELLED"},
            "PENDING_PAYMENT": {"CANCELLED"},
        }
        if payload.status not in allowed.get(booking.status, set()):
            raise BookingStateError(
                f"Booking cannot move from {booking.status} to {payload.status}."
            )
        booking.status = payload.status
    if "notes" in payload.model_fields_set:
        booking.notes = payload.notes
    await audit.record(
        db,
        actor_id=admin.id,
        action="booking.update",
        target_type="booking",
        target_id=booking.id,
        metadata={"statusFrom": before, "statusTo": booking.status},
        ip=_ip(request),
    )
    await db.commit()
    return BookingOut.model_validate(booking)


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _csv_response(name: str, headers: list[str], rows: list[tuple]) -> StreamingResponse:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows([[_csv_safe(v) for v in row] for row in rows])
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="zent-{name}.csv"'},
    )


@router.get("/reports/{report_name}.csv", response_class=StreamingResponse)
async def export_report(report_name: str, db: DbSession, _admin: AdminUser) -> StreamingResponse:
    if report_name == "payments":
        rows = (
            await db.execute(
                select(
                    Payment.id,
                    Payment.reference,
                    Payment.booking_id,
                    Payment.provider,
                    Payment.amount,
                    Payment.currency,
                    Payment.status,
                    Payment.created_at,
                ).order_by(Payment.created_at.desc())
            )
        ).all()
        return _csv_response(
            report_name,
            [
                "id",
                "reference",
                "booking_id",
                "provider",
                "amount",
                "currency",
                "status",
                "created_at",
            ],
            list(rows),
        )
    if report_name == "bookings":
        rows = (
            await db.execute(
                select(
                    Booking.id,
                    Booking.confirmation_code,
                    Booking.property_id,
                    Booking.guest_name,
                    Booking.guest_email,
                    Booking.check_in,
                    Booking.check_out,
                    Booking.total_amount,
                    Booking.status,
                    Booking.created_at,
                ).order_by(Booking.created_at.desc())
            )
        ).all()
        return _csv_response(
            report_name,
            [
                "id",
                "confirmation_code",
                "property_id",
                "guest_name",
                "guest_email",
                "check_in",
                "check_out",
                "total_amount",
                "status",
                "created_at",
            ],
            list(rows),
        )
    if report_name == "payouts":
        rows = (
            await db.execute(
                select(
                    PayoutRequest.id,
                    PayoutRequest.agent_id,
                    PayoutRequest.amount,
                    PayoutRequest.currency,
                    PayoutRequest.status,
                    PayoutRequest.bank_name,
                    PayoutRequest.account_number,
                    PayoutRequest.created_at,
                ).order_by(PayoutRequest.created_at.desc())
            )
        ).all()
        return _csv_response(
            report_name,
            [
                "id",
                "agent_id",
                "amount",
                "currency",
                "status",
                "bank_name",
                "account_number",
                "created_at",
            ],
            list(rows),
        )
    raise AppError(404, "report_not_found", "Report must be payments, bookings, or payouts.")


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
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
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
        db,
        actor_id=admin.id,
        action="role.change",
        target_type="user",
        target_id=user_id,
        metadata={"from": before, "to": payload.role},
        ip=_ip(request),
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
        db,
        actor_id=admin.id,
        action="user.activate" if payload.is_active else "user.deactivate",
        target_type="user",
        target_id=user_id,
        ip=_ip(request),
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
        db,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        role=payload.role,
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action="agent.invite",
        target_type="user",
        target_id=user.id,
        metadata={"role": payload.role, "email": user.email},
        ip=_ip(request),
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


@router.get("/users/{user_id}/profile", response_model=AgentProfileOut)
async def get_user_profile(user_id: str, db: DbSession, _admin: AdminUser) -> AgentProfileOut:
    await staff_service.get_user(db, user_id)
    profile = await staff_service.get_or_create_profile(db, user_id)
    await db.commit()
    return AgentProfileOut.model_validate(profile)


@router.put("/users/{user_id}/profile", response_model=AgentProfileOut)
async def update_user_profile(
    user_id: str, payload: AgentProfileUpdate, db: DbSession, admin: AdminUser, request: Request
) -> AgentProfileOut:
    await staff_service.get_user(db, user_id)
    profile = await staff_service.update_profile(
        db, user_id, payload.model_dump(exclude_unset=True)
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action="agent.profile_edit",
        target_type="user",
        target_id=user_id,
        ip=_ip(request),
    )
    await db.commit()
    return AgentProfileOut.model_validate(profile)


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
        db,
        actor_id=admin.id,
        action="agent.assign",
        target_type="property",
        target_id=property_id,
        metadata={"agentId": payload.agent_id},
        ip=_ip(request),
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
        db,
        actor_id=admin.id,
        action="agent.unassign",
        target_type="property",
        target_id=property_id,
        metadata={"agentId": agent_id},
        ip=_ip(request),
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
        page=page,
        limit=limit,
    )
    return AttendanceListResponse(
        records=[AttendanceOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
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
        db,
        attendance_id,
        clock_in_at=payload.clock_in_at,
        clock_out_at=payload.clock_out_at,
        note=payload.note,
    )
    await audit.record(
        db,
        actor_id=admin.id,
        action="attendance.edit",
        target_type="attendance",
        target_id=attendance_id,
        metadata=payload.model_dump(exclude_unset=True, mode="json"),
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
                stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    entries = [
        AuditEntryOut(
            id=r.id,
            actor_user_id=r.actor_user_id,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            metadata=r.audit_metadata,
            ip=r.ip,
            created_at=r.created_at,
        )
        for r in rows
    ]
    pages = (total + limit - 1) // limit if limit else 0
    return AuditListResponse(
        entries=entries, total=total, page=page, limit=limit, total_pages=pages
    )
