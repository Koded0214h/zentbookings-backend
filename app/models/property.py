from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin, _utcnow

# Values the PRD's Property model constrains to a closed set.
PERIODS = ("Per Month", "Per Night")
CATEGORIES = ("Rent", "Shortlet")


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
    year_built: Mapped[int] = mapped_column(Integer, nullable=False)
    amenities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    full_description: Mapped[str] = mapped_column(Text, nullable=False)
    dot_color: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # Cloudinary bookkeeping — not exposed in PropertyOut; used to clean up
    # assets when a property is deleted.
    image_public_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gallery_public_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
