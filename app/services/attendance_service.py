from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.staff import StaffAttendance


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class AttendanceStateError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "attendance_state", message)


class AttendanceNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "attendance_not_found", "Attendance record not found.")


@dataclass(slots=True)
class AttendanceFilters:
    user_id: str | None = None
    status: str | None = None  # "open" | "closed"
    date_from: datetime | None = None
    date_to: datetime | None = None


async def open_session(db: AsyncSession, user_id: str) -> StaffAttendance | None:
    return await db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.user_id == user_id,
            StaffAttendance.clock_out_at.is_(None),
        )
    )


async def clock_in(
    db: AsyncSession,
    user_id: str,
    *,
    source: str = "web",
    ip: str | None = None,
    user_agent: str | None = None,
) -> StaffAttendance:
    if await open_session(db, user_id):
        raise AttendanceStateError("You are already clocked in.")
    row = StaffAttendance(
        user_id=user_id,
        clock_in_at=_utcnow(),
        source=source if source in ("web", "mobile", "api") else "web",
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(row)
    await db.flush()
    return row


async def clock_out(db: AsyncSession, user_id: str) -> StaffAttendance:
    row = await open_session(db, user_id)
    if row is None:
        raise AttendanceStateError("You are not clocked in.")
    row.clock_out_at = _utcnow()
    row.duration_minutes = _minutes(row.clock_in_at, row.clock_out_at)
    await db.flush()
    return row


def _minutes(start: datetime, end: datetime) -> int:
    return max(0, int((_aware(end) - _aware(start)).total_seconds() // 60))


async def status_for(db: AsyncSession, user_id: str) -> dict:
    row = await open_session(db, user_id)
    since_utc = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    closed_today = (
        await db.scalar(
            select(func.coalesce(func.sum(StaffAttendance.duration_minutes), 0)).where(
                StaffAttendance.user_id == user_id,
                StaffAttendance.clock_in_at >= since_utc,
                StaffAttendance.clock_out_at.isnot(None),
            )
        )
        or 0
    )
    open_minutes = _minutes(row.clock_in_at, _utcnow()) if row else 0
    return {
        "clocked_in": row is not None,
        "since": _aware(row.clock_in_at) if row else None,
        "today_minutes": int(closed_today) + open_minutes,
    }


def _apply(stmt, f: AttendanceFilters):
    if f.user_id:
        stmt = stmt.where(StaffAttendance.user_id == f.user_id)
    if f.status == "open":
        stmt = stmt.where(StaffAttendance.clock_out_at.is_(None))
    elif f.status == "closed":
        stmt = stmt.where(StaffAttendance.clock_out_at.isnot(None))
    if f.date_from:
        stmt = stmt.where(StaffAttendance.clock_in_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(StaffAttendance.clock_in_at < f.date_to)
    return stmt


async def list_attendance(
    db: AsyncSession, *, filters: AttendanceFilters, page: int, limit: int
) -> tuple[list[StaffAttendance], int, int]:
    total = int(
        await db.scalar(_apply(select(func.count()).select_from(StaffAttendance), filters)) or 0
    )
    rows = (
        (
            await db.execute(
                _apply(select(StaffAttendance), filters)
                .order_by(StaffAttendance.clock_in_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0


async def summary(
    db: AsyncSession, *, date_from: datetime, date_to: datetime
) -> list[dict]:
    rows = (
        await db.execute(
            select(
                StaffAttendance.user_id,
                func.count().label("sessions"),
                func.coalesce(func.sum(StaffAttendance.duration_minutes), 0).label("minutes"),
            )
            .where(
                StaffAttendance.clock_in_at >= date_from,
                StaffAttendance.clock_in_at < date_to,
                StaffAttendance.clock_out_at.isnot(None),
            )
            .group_by(StaffAttendance.user_id)
        )
    ).all()
    return [
        {"user_id": uid, "sessions": int(sessions), "total_minutes": int(minutes)}
        for uid, sessions, minutes in rows
    ]


async def edit(
    db: AsyncSession,
    attendance_id: str,
    *,
    clock_in_at: datetime | None = None,
    clock_out_at: datetime | None = None,
    note: str | None = None,
) -> StaffAttendance:
    row = await db.get(StaffAttendance, attendance_id)
    if row is None:
        raise AttendanceNotFound()
    if clock_in_at is not None:
        row.clock_in_at = clock_in_at
    if clock_out_at is not None:
        row.clock_out_at = clock_out_at
    if note is not None:
        row.note = note
    if row.clock_out_at is not None:
        if _aware(row.clock_out_at) < _aware(row.clock_in_at):
            raise AttendanceStateError("clock_out cannot precede clock_in.")
        row.duration_minutes = _minutes(row.clock_in_at, row.clock_out_at)
    else:
        row.duration_minutes = None
    await db.flush()
    return row


async def close_stale(
    db: AsyncSession, *, older_than_hours: int, now: datetime | None = None
) -> int:
    now = now or _utcnow()
    cutoff = now - timedelta(hours=older_than_hours)
    rows = (
        (
            await db.execute(
                select(StaffAttendance).where(
                    StaffAttendance.clock_out_at.is_(None),
                    StaffAttendance.clock_in_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.clock_out_at = _aware(row.clock_in_at) + timedelta(hours=older_than_hours)
        row.duration_minutes = older_than_hours * 60
        row.auto_closed = True
    if rows:
        await db.flush()
    return len(rows)
