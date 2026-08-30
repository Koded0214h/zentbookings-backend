from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel

Period = Literal["Per Month", "Per Night"]
Category = Literal["Rent", "Shortlet"]


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


class PropertyCreate(PropertyBase):
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
    image_public_id: str | None = Field(default=None, max_length=255)
    gallery_public_ids: list[str] | None = None


class PropertyOut(PropertyBase):
    id: int


class PropertyListResponse(CamelModel):
    properties: list[PropertyOut]
    total: int
    page: int
    limit: int
    total_pages: int
