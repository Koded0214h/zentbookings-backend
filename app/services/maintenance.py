from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import EmailVerificationToken, OAuthState, PasswordResetToken, TokenDenylist

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


async def run_cleanup_once() -> dict[str, int]:
    """One purge pass using the app's own engine. Usable from a cron/CLI."""
    async with SessionLocal() as db:
        counts = await purge_expired(db)
    if any(counts.values()):
        logger.info("[maintenance] purged expired rows: %s", counts)
    return counts


async def cleanup_loop(stop: asyncio.Event) -> None:
    """Background loop: purge expired rows every CLEANUP_INTERVAL_SECONDS."""
    while not stop.is_set():
        try:
            await run_cleanup_once()
        except Exception:  # never let the loop die on a transient DB error
            logger.exception("[maintenance] cleanup pass failed")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.CLEANUP_INTERVAL_SECONDS)
