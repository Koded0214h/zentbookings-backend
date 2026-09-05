from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.database import Base
from app.models.user import TimestampMixin, _utcnow

# Values the PRD's Property model constrains to a closed set.
PERIODS = ("Per Month", "Per Night")
CATEGORIES = ("Rent", "Shortlet")
# Frontend "Type" filter — free string, but these are the values we seed / derive.
PROPERTY_TYPES = ("Monthly", "Yearly", "Nightly", "Weekly")

_PERIOD_TO_TYPE = {"Per Month": "Monthly", "Per Night": "Nightly"}


def derive_type(period: str) -> str:
    return _PERIOD_TO_TYPE.get(period, "Monthly")


class Property(TimestampMixin, Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    image: Mapped[str] = mapped_column(String(1024), nullable=False)
    gallery: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    beds: Mapped[int] = mapped_column(Integer, nullable=False)
    baths: Mapped[int] = mapped_column(Integer, nullable=False)
    sqft: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    year_built: Mapped[int] = mapped_column(Integer, nullable=False)
    amenities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # lowercase "a | b | c" mirror of `amenities`, kept in sync by the validator
    # below so we can filter with a portable ILIKE instead of JSON containment.
    amenities_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    full_description: Mapped[str] = mapped_column(Text, nullable=False)
    dot_color: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    created_by_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )

    # Cloudinary bookkeeping — not exposed in PropertyOut; used to clean up
    # assets when a property is hard-deleted.
    image_public_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gallery_public_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    @validates("amenities")
    def _sync_amenities_text(self, _key: str, value: list[str] | None) -> list[str] | None:
        self.amenities_text = " | ".join(str(a).lower() for a in (value or []))
        return value
