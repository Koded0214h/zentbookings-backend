from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.tour import (
    ACTIVE_TOUR_STATUSES,
    WEEKDAY_KEYS,
    PropertySchedule,
    Tour,
)


class SlotUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "slot_unavailable", message)


@dataclass(slots=True)
class Slot:
    date: str        # YYYY-MM-DD (local)
    time: str        # HH:MM (local)
    scheduled_at: datetime  # UTC, tz-aware
    available: int
    capacity: int


def _tz(schedule: PropertySchedule) -> ZoneInfo:
    try:
        return ZoneInfo(schedule.timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


async def get_or_create_schedule(db: AsyncSession, property_id: int) -> PropertySchedule:
    schedule = await db.get(PropertySchedule, property_id)
    if schedule is None:
        schedule = PropertySchedule(property_id=property_id)
        db.add(schedule)
        await db.flush()
    return schedule


def local_to_utc(schedule: PropertySchedule, d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=_tz(schedule)).astimezone(UTC)


def slot_times_for_date(schedule: PropertySchedule, d: date) -> list[time]:
    """Expand the weekday's open ranges into slot start times."""
    key = WEEKDAY_KEYS[d.weekday()]
    step = timedelta(minutes=schedule.slot_duration_minutes)
    out: list[time] = []
    for start_s, end_s in schedule.weekly_hours.get(key, []):
        cur = datetime.combine(d, _parse_hhmm(start_s))
        end = datetime.combine(d, _parse_hhmm(end_s))
        while cur + step <= end:
            out.append(cur.time())
            cur += step
    return out


def _date_in_window(schedule: PropertySchedule, d: date, now_local: datetime) -> bool:
    if d.isoformat() in (schedule.blackout_dates or []):
        return False
    today = now_local.date()
    if d < today:
        return False
    if d > today + timedelta(days=schedule.advance_booking_days):
        return False
    return True


async def _active_counts(
    db: AsyncSession, property_id: int, start_utc: datetime, end_utc: datetime
) -> dict[datetime, int]:
    rows = (
        await db.execute(
            select(Tour.scheduled_at, func.count())
            .where(
                Tour.property_id == property_id,
                Tour.status.in_(ACTIVE_TOUR_STATUSES),
                Tour.scheduled_at >= start_utc,
                Tour.scheduled_at < end_utc,
            )
            .group_by(Tour.scheduled_at)
        )
    ).all()
    out: dict[datetime, int] = {}
    for dt, count in rows:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        out[dt] = count
    return out


async def availability(
    db: AsyncSession,
    schedule: PropertySchedule,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    now: datetime | None = None,
) -> list[Slot]:
    now = now or datetime.now(UTC)
    now_local = now.astimezone(_tz(schedule))
    from_date = from_date or now_local.date()
    to_date = to_date or (now_local.date() + timedelta(days=schedule.advance_booking_days))

    start_utc = local_to_utc(schedule, from_date, time(0, 0))
    end_utc = local_to_utc(schedule, to_date + timedelta(days=1), time(0, 0))
    counts = await _active_counts(db, schedule.property_id, start_utc, end_utc)

    slots: list[Slot] = []
    d = from_date
    while d <= to_date:
        if _date_in_window(schedule, d, now_local):
            for t in slot_times_for_date(schedule, d):
                dt_utc = local_to_utc(schedule, d, t)
                if dt_utc <= now + timedelta(hours=schedule.min_notice_hours):
                    continue
                used = counts.get(dt_utc, 0)
                slots.append(
                    Slot(
                        date=d.isoformat(),
                        time=t.strftime("%H:%M"),
                        scheduled_at=dt_utc,
                        available=max(0, schedule.capacity_per_slot - used),
                        capacity=schedule.capacity_per_slot,
                    )
                )
        d += timedelta(days=1)
    return slots


async def resolve_and_validate_slot(
    db: AsyncSession,
    schedule: PropertySchedule,
    *,
    d: date,
    t: time,
    now: datetime | None = None,
) -> datetime:
    """Return the UTC scheduled_at for a requested slot, or raise SlotUnavailable."""
    now = now or datetime.now(UTC)
    now_local = now.astimezone(_tz(schedule))

    if not _date_in_window(schedule, d, now_local):
        raise SlotUnavailable("That date is not open for tours.")
    if t not in slot_times_for_date(schedule, d):
        raise SlotUnavailable("That time is not a bookable slot.")

    dt_utc = local_to_utc(schedule, d, t)
    if dt_utc <= now + timedelta(hours=schedule.min_notice_hours):
        raise SlotUnavailable(
            f"Tours must be booked at least {schedule.min_notice_hours} hours ahead."
        )

    counts = await _active_counts(
        db, schedule.property_id, dt_utc, dt_utc + timedelta(seconds=1)
    )
    if counts.get(dt_utc, 0) >= schedule.capacity_per_slot:
        raise SlotUnavailable("That slot is fully booked.")
    return dt_utc
