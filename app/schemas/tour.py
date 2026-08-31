from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from typing import Literal

from pydantic import EmailStr, Field, field_serializer, field_validator

from app.schemas.common import CamelModel

Status = Literal["PENDING", "CONFIRMED", "CANCELLED"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _iso_z(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Booking --------------------------------------------------------------
class TourCreate(CamelModel):
    property_id: int
    visitor_name: str | None = Field(default=None, max_length=200)
    visitor_email: EmailStr | None = None
    visitor_phone: str | None = Field(default=None, max_length=40)
    scheduled_date: date
    scheduled_time: str
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("scheduled_time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("scheduledTime must be HH:MM (24h)")
        return v

    def time_obj(self) -> time:
        hh, mm = self.scheduled_time.split(":")
        return time(int(hh), int(mm))


class TourCreateResponse(CamelModel):
    id: str
    property_id: int
    status: Status
    scheduled_at: datetime
    confirmation_code: str

    @field_serializer("scheduled_at", when_used="json")
    def _ser_scheduled_at(self, v: datetime) -> str | None:
        return _iso_z(v)


class TourOut(CamelModel):
    id: str
    property_id: int
    user_id: str | None = None
    visitor_name: str
    visitor_email: EmailStr
    visitor_phone: str
    scheduled_at: datetime
    notes: str | None = None
    status: Status
    confirmation_code: str
    created_at: datetime | None = None

    @field_serializer("scheduled_at", "created_at", when_used="json")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class TourListResponse(CamelModel):
    tours: list[TourOut]
    total: int
    page: int
    limit: int
    total_pages: int


class GuestTourAction(CamelModel):
    confirmation_code: str = Field(min_length=1)
    email: EmailStr


# --- Availability -------------------------------------------------------------
class SlotOut(CamelModel):
    date: str
    time: str
    available: int
    capacity: int


class AvailabilityResponse(CamelModel):
    property_id: int
    timezone: str
    slots: list[SlotOut]


# --- Schedule config (staff) --------------------------------------------
class ScheduleOut(CamelModel):
    property_id: int
    timezone: str
    slot_duration_minutes: int
    capacity_per_slot: int
    auto_confirm: bool
    advance_booking_days: int
    min_notice_hours: int
    weekly_hours: dict[str, list[list[str]]]
    blackout_dates: list[str]


class ScheduleUpdate(CamelModel):
    timezone: str | None = Field(default=None, max_length=64)
    slot_duration_minutes: int | None = Field(default=None, ge=15, le=480)
    capacity_per_slot: int | None = Field(default=None, ge=1, le=100)
    auto_confirm: bool | None = None
    advance_booking_days: int | None = Field(default=None, ge=1, le=365)
    min_notice_hours: int | None = Field(default=None, ge=0, le=720)
    weekly_hours: dict[str, list[list[str]]] | None = None
    blackout_dates: list[str] | None = None

    @field_validator("weekly_hours")
    @classmethod
    def _valid_hours(cls, v):
        if v is None:
            return v
        valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        for day, ranges in v.items():
            if day not in valid_days:
                raise ValueError(f"unknown weekday key: {day}")
            for rng in ranges:
                if len(rng) != 2 or not all(_HHMM.match(x) for x in rng):
                    raise ValueError(f"{day}: ranges must be [HH:MM, HH:MM]")
                if rng[0] >= rng[1]:
                    raise ValueError(f"{day}: range start must precede end")
        return v

    @field_validator("blackout_dates")
    @classmethod
    def _valid_blackouts(cls, v):
        if v is None:
            return v
        for s in v:
            try:
                date.fromisoformat(s)
            except ValueError as exc:
                raise ValueError(f"blackout date not YYYY-MM-DD: {s}") from exc
        return v
