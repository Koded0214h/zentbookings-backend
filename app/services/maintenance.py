from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.property import Property
from app.models.staff import AuditLog
from app.models.user import EmailVerificationToken, OAuthState, PasswordResetToken, TokenDenylist
from app.services import attendance_service, media

logger = logging.getLogger("zent.maintenance")

# Tables with an `expires_at` column that are safe to prune once past it.
_EXPIRABLE = (TokenDenylist, OAuthState, EmailVerificationToken, PasswordResetToken)


async def purge_expired(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Delete rows whose expires_at is in the past. Returns per-table counts."""
    now = now or datetime.now(UTC)
    counts: dict[str, int] = {}
    for model in _EXPIRABLE:
        result = await db.execute(delete(model).where(model.expires_at < now))
        counts[model.__tablename__] = result.rowcount or 0
    await db.commit()
    return counts


async def _referenced_public_ids(db: AsyncSession) -> set[str]:
    rows = (
        await db.execute(
            select(
                Property.image,
                Property.gallery,
                Property.image_public_id,
                Property.gallery_public_ids,
            )
        )
    ).all()
    ids: set[str] = set()
    for image, gallery, image_pid, gallery_pids in rows:
        if image_pid:
            ids.add(image_pid)
        ids.update(gallery_pids or [])
        for url in (image, *(gallery or [])):
            pid = media.public_id_from_url(url)
            if pid:
                ids.add(pid)
    return ids


def _cloudinary_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def sweep_orphan_media(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Destroy Cloudinary assets in the folder that no property references and
    that are older than the grace period. Returns the count removed."""
    if not settings.MEDIA_SWEEP_ENABLED or not settings.cloudinary_configured:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.MEDIA_SWEEP_GRACE_SECONDS)
    referenced = await _referenced_public_ids(db)

    removed = 0
    for resource_type in ("image", "video"):
        for asset in await media.list_assets(resource_type=resource_type):
            pid = asset.get("public_id")
            if not pid or pid in referenced:
                continue
            created = asset.get("created_at")
            if created and _cloudinary_dt(created) > cutoff:
                continue  # too fresh — may not be attached yet
            if await media.destroy(pid, resource_type=resource_type):
                removed += 1
    if removed:
        logger.info("[maintenance] swept %d orphan media asset(s)", removed)
    return removed


async def prune_audit(db: AsyncSession, *, now: datetime | None = None) -> int:
    if settings.AUDIT_RETENTION_DAYS <= 0:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.AUDIT_RETENTION_DAYS)
    result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0


async def run_cleanup_once() -> dict[str, int]:
    """One maintenance pass using the app's own engine. Usable from a cron/CLI."""
    async with SessionLocal() as db:
        counts = await purge_expired(db)
        counts["stale_attendance"] = await attendance_service.close_stale(
            db, older_than_hours=settings.ATTENDANCE_AUTO_CLOSE_HOURS
        )
        await db.commit()
        counts["pruned_audit"] = await prune_audit(db)
        try:
            counts["orphan_media"] = await sweep_orphan_media(db)
        except Exception:
            logger.exception("[maintenance] media sweep failed")
            counts["orphan_media"] = 0
    if any(counts.values()):
        logger.info("[maintenance] purged: %s", counts)
    return counts


async def cleanup_loop(stop: asyncio.Event) -> None:
    """Background loop: run a maintenance pass every CLEANUP_INTERVAL_SECONDS."""
    while not stop.is_set():
        try:
            await run_cleanup_once()
        except Exception:  # never let the loop die on a transient error
            logger.exception("[maintenance] cleanup pass failed")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.CLEANUP_INTERVAL_SECONDS)
