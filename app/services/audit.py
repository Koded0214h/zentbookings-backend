from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_id: str | None,
    action: str,
    target_type: str,
    target_id: str | int,
    metadata: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit row in the caller's transaction (commits with the mutation)."""
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            audit_metadata=metadata or {},
            ip=ip,
        )
    )
    await db.flush()
