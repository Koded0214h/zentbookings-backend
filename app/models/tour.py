from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin, _utcnow, gen_id

TOUR_STATUSES = ("PENDING", "CONFIRMED", "CANCELLED")
ACTIVE_TOUR_STATUSES = ("PENDING", "CONFIRMED")

# Mon..Sun keys used by PropertySchedule.weekly_hours
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_WEEKLY_HOURS: dict[str, list[list[str]]] = {
    "mon": [["10:00", "17:00"]],
    "tue": [["10:00", "17:00"]],
    "wed": [["10:00", "17:00"]],
    "thu": [["10:00", "17:00"]],
    "fri": [["10:00", "17:00"]],
    "sat": [["11:00", "15:00"]],
    "sun": [],
}


class PropertySchedule(TimestampMixin, Base):
    """Per-property tour availability config. One row per property, lazily created."""

    __tablename__ = "property_schedules"

    property_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos", nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    capacity_per_slot: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    auto_confirm: Mapped[bool] = mapped_column(default=True, nullable=False)
    advance_booking_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    # {"mon": [["10:00","17:00"]], ...}; missing/empty weekday = closed
    weekly_hours: Mapped[dict] = mapped_column(
        JSON, default=lambda: dict(DEFAULT_WEEKLY_HOURS), nullable=False
    )
    blackout_dates: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Tour(TimestampMixin, Base):
    __tablename__ = "tours"
    __table_args__ = (
        Index("ix_tours_property_slot", "property_id", "scheduled_at"),
        Index("ix_tours_user_id", "user_id"),
        Index("ix_tours_visitor_email", "visitor_email"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("tour"))
    property_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visitor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    visitor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    visitor_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    confirmation_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
