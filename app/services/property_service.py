from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.property import Property
from app.schemas.property import PropertyCreate, PropertyUpdate

# PRD's Property model has no `type` field; the ?type= filter maps onto `period`.
_TYPE_TO_PERIOD = {
    "monthly": "Per Month",
    "month": "Per Month",
    "per month": "Per Month",
    "rent": "Per Month",
    "nightly": "Per Night",
    "night": "Per Night",
    "per night": "Per Night",
    "shortlet": "Per Night",
}

_SORTS = {
    "id": (Property.id.asc(),),
    "-id": (Property.id.desc(),),
    "price": (Property.price.asc(), Property.id.asc()),
    "-price": (Property.price.desc(), Property.id.asc()),
    "newest": (Property.created_at.desc(), Property.id.desc()),
    "oldest": (Property.created_at.asc(), Property.id.asc()),
}
SORT_OPTIONS = tuple(_SORTS)


class PropertyNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "property_not_found", "Property not found.")


@dataclass(slots=True)
class PropertyFilters:
    category: str | None = None
    location: str | None = None
    type: str | None = None
    price_min: int | None = None
    price_max: int | None = None
    q: str | None = None


def _apply_filters(stmt, f: PropertyFilters):
    if f.category:
        stmt = stmt.where(func.lower(Property.category) == f.category.lower())
    if f.location:
        stmt = stmt.where(Property.location.ilike(f"%{f.location}%"))
    if f.type:
        period = _TYPE_TO_PERIOD.get(f.type.strip().lower())
        if period:
            stmt = stmt.where(Property.period == period)
    if f.price_min is not None:
        stmt = stmt.where(Property.price >= f.price_min)
    if f.price_max is not None:
        stmt = stmt.where(Property.price <= f.price_max)
    if f.q:
        term = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(
                Property.title.ilike(term),
                Property.location.ilike(term),
                Property.description.ilike(term),
            )
        )
    return stmt


async def list_properties(
    db: AsyncSession,
    *,
    filters: PropertyFilters,
    page: int,
    limit: int,
    sort: str = "id",
) -> tuple[list[Property], int, int]:
    total = int(
        await db.scalar(
            _apply_filters(select(func.count()).select_from(Property), filters)
        )
        or 0
    )

    rows = (
        (
            await db.execute(
                _apply_filters(select(Property), filters)
                .order_by(*_SORTS.get(sort, _SORTS["id"]))
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    total_pages = ceil(total / limit) if limit else 0
    return list(rows), total, total_pages


async def get_property(db: AsyncSession, property_id: int) -> Property:
    row = await db.get(Property, property_id)
    if row is None:
        raise PropertyNotFound()
    return row


async def create_property(db: AsyncSession, data: PropertyCreate) -> Property:
    row = Property(**data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def update_property(
    db: AsyncSession, property_id: int, data: PropertyUpdate
) -> Property:
    row = await get_property(db, property_id)
    changes = data.model_dump(exclude_unset=True)

    old_image_pid = row.image_public_id
    old_gallery_pids = set(row.gallery_public_ids or [])

    for key, value in changes.items():
        setattr(row, key, value)
    await db.flush()

    # destroy assets that this update dereferenced
    orphans: set[str] = set()
    if "image_public_id" in changes and old_image_pid and old_image_pid != row.image_public_id:
        orphans.add(old_image_pid)
    if "gallery_public_ids" in changes:
        orphans |= old_gallery_pids - set(row.gallery_public_ids or [])
    orphans.discard(row.image_public_id or "")
    await _cleanup_assets(orphans - set(row.gallery_public_ids or []))
    return row


async def delete_property(db: AsyncSession, property_id: int) -> None:
    row = await get_property(db, property_id)
    public_ids = set(row.gallery_public_ids or [])
    if row.image_public_id:
        public_ids.add(row.image_public_id)

    await db.delete(row)
    await db.flush()
    await _cleanup_assets(public_ids)


async def _cleanup_assets(public_ids) -> None:
    ids = [p for p in public_ids if p]
    if not ids or not settings.cloudinary_configured:
        return
    from app.services import media

    for pid in ids:
        await media.destroy(pid)  # best-effort; never blocks the write
