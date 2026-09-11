from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel

Period = Literal["Per Month", "Per Night"]
Category = Literal["Rent", "Shortlet"]
CancellationPolicy = Literal["Flexible", "Moderate", "Strict"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _valid_hhmm(v: str | None) -> str | None:
    if v is not None and not _HHMM.match(v):
        raise ValueError("must be HH:MM (24h)")
    return v


class PropertyBase(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    image: str = Field(min_length=1, max_length=1024)
    gallery: list[str] = Field(default_factory=list)
    beds: int = Field(ge=0, le=50)
    baths: int = Field(ge=0, le=50)
    sqft: int = Field(ge=0, le=1_000_000)
    price: int = Field(ge=0)
    period: Period
    year_built: int = Field(ge=1800, le=2100)
    amenities: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1, max_length=500)
    full_description: str = Field(min_length=1)
    dot_color: str = Field(min_length=1, max_length=20)
    category: Category

    # --- structured location (Module 5.1) -----------------------------------
    street_address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state_region: str | None = Field(default=None, max_length=120)
    zip_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=120)

    # --- short-let booking policy (Module 5.1) ------------------------------
    cleaning_fee: int = Field(default=0, ge=0)
    security_deposit: int = Field(default=0, ge=0)
    minimum_stay_nights: int = Field(default=1, ge=1, le=365)
    cancellation_policy: CancellationPolicy = "Flexible"
    check_in_time: str | None = Field(default=None, max_length=5)
    check_out_time: str | None = Field(default=None, max_length=5)
    max_guests: int = Field(default=1, ge=1, le=100)
    pets_allowed: bool = False

    _check_in = field_validator("check_in_time")(_valid_hhmm)
    _check_out = field_validator("check_out_time")(_valid_hhmm)


class PropertyCreate(PropertyBase):
    # Free string (e.g. Monthly / Yearly / Nightly / Weekly). Derived from
    # `period` when omitted.
    type: str | None = Field(default=None, max_length=20)
    # Optional Cloudinary public ids (from POST /media/upload). Stored, not echoed;
    # used to delete the assets when the property is removed.
    image_public_id: str | None = Field(default=None, max_length=255)
    gallery_public_ids: list[str] = Field(default_factory=list)


class PropertyUpdate(CamelModel):
    """All fields optional; only provided keys are applied."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    image: str | None = Field(default=None, min_length=1, max_length=1024)
    gallery: list[str] | None = None
    beds: int | None = Field(default=None, ge=0, le=50)
    baths: int | None = Field(default=None, ge=0, le=50)
    sqft: int | None = Field(default=None, ge=0, le=1_000_000)
    price: int | None = Field(default=None, ge=0)
    period: Period | None = None
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    amenities: list[str] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    full_description: str | None = Field(default=None, min_length=1)
    dot_color: str | None = Field(default=None, min_length=1, max_length=20)
    category: Category | None = None
    type: str | None = Field(default=None, max_length=20)
    image_public_id: str | None = Field(default=None, max_length=255)
    gallery_public_ids: list[str] | None = None

    street_address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state_region: str | None = Field(default=None, max_length=120)
    zip_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=120)

    cleaning_fee: int | None = Field(default=None, ge=0)
    security_deposit: int | None = Field(default=None, ge=0)
    minimum_stay_nights: int | None = Field(default=None, ge=1, le=365)
    cancellation_policy: CancellationPolicy | None = None
    check_in_time: str | None = Field(default=None, max_length=5)
    check_out_time: str | None = Field(default=None, max_length=5)
    max_guests: int | None = Field(default=None, ge=1, le=100)
    pets_allowed: bool | None = None

    _check_in = field_validator("check_in_time")(_valid_hhmm)
    _check_out = field_validator("check_out_time")(_valid_hhmm)


class PropertyOut(PropertyBase):
    id: int
    type: str
    created_by_id: str | None = None


class PropertyListResponse(CamelModel):
    properties: list[PropertyOut]
    total: int
    page: int
    limit: int
    total_pages: int
