from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.property import Property
from app.models.staff import AgentProfile, PropertyAgent
from app.models.user import User
from app.services import auth_service

ROLES = ("user", "agent", "admin")
STAFF_ROLES = ("agent", "admin")


class UserNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "user_not_found", "User not found.")


class LastAdmin(AppError):
    def __init__(self) -> None:
        super().__init__(409, "last_admin", "Cannot remove the last active admin.")


@dataclass(slots=True)
class UserFilters:
    role: str | None = None
    is_active: bool | None = None
    q: str | None = None


def _apply(stmt, f: UserFilters):
    if f.role:
        stmt = stmt.where(User.role == f.role)
    if f.is_active is not None:
        stmt = stmt.where(User.is_active.is_(f.is_active))
    if f.q:
        term = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(User.email.ilike(term), User.first_name.ilike(term), User.last_name.ilike(term))
        )
    return stmt


async def list_users(
    db: AsyncSession, *, filters: UserFilters, page: int, limit: int
) -> tuple[list[User], int, int]:
    total = int(await db.scalar(_apply(select(func.count()).select_from(User), filters)) or 0)
    rows = (
        (
            await db.execute(
                _apply(select(User), filters)
                .order_by(User.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0


async def get_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFound()
    return user


async def _other_active_admins(db: AsyncSession, exclude_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.is_active.is_(True), User.id != exclude_id
            )
        )
        or 0
    )


async def set_role(db: AsyncSession, user: User, new_role: str) -> User:
    if new_role not in ROLES:
        raise AppError(422, "validation_error", f"role must be one of {ROLES}")
    if (
        user.role == "admin"
        and user.is_active
        and new_role != "admin"
        and await _other_active_admins(db, user.id) == 0
    ):
        raise LastAdmin()
    user.role = new_role
    await db.flush()
    return user


async def set_status(db: AsyncSession, user: User, is_active: bool) -> User:
    if (
        user.role == "admin"
        and user.is_active
        and not is_active
        and await _other_active_admins(db, user.id) == 0
    ):
        raise LastAdmin()
    user.is_active = is_active
    await db.flush()
    return user


async def invite_staff(
    db: AsyncSession, *, first_name: str, last_name: str, email: str, role: str
) -> tuple[User, str]:
    if role not in STAFF_ROLES:
        raise AppError(422, "validation_error", f"role must be one of {STAFF_ROLES}")
    if await auth_service.get_user_by_email(db, email):
        from app.core.exceptions import EmailAlreadyExists

        raise EmailAlreadyExists()
    user = User(
        email=auth_service.normalize_email(email),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=role,
        is_verified=True,
        hashed_password=None,
    )
    db.add(user)
    await db.flush()
    raw_token = await auth_service.issue_password_reset_token(db, user)
    return user, raw_token


# --- Agent <-> property assignment (soft) -------------------------------
async def assign_agent(db: AsyncSession, *, property_id: int, agent_id: str, by: str) -> None:
    if await db.get(Property, property_id) is None:
        raise AppError(404, "property_not_found", "Property not found.")
    agent = await db.get(User, agent_id)
    if agent is None or agent.role not in STAFF_ROLES:
        raise AppError(422, "validation_error", "Target user is not a staff member.")
    if await db.get(PropertyAgent, (property_id, agent_id)) is None:
        db.add(PropertyAgent(property_id=property_id, agent_id=agent_id, assigned_by=by))
        await db.flush()


async def unassign_agent(db: AsyncSession, *, property_id: int, agent_id: str) -> None:
    row = await db.get(PropertyAgent, (property_id, agent_id))
    if row is not None:
        await db.delete(row)
        await db.flush()


async def assigned_property_ids(db: AsyncSession, agent_id: str) -> list[int]:
    rows = await db.execute(
        select(PropertyAgent.property_id).where(PropertyAgent.agent_id == agent_id)
    )
    return [r[0] for r in rows.all()]


async def property_agent_ids(db: AsyncSession, property_id: int) -> list[str]:
    rows = await db.execute(
        select(PropertyAgent.agent_id).where(PropertyAgent.property_id == property_id)
    )
    return [r[0] for r in rows.all()]


# --- Agent public profile --------------------------------------------------
async def get_or_create_profile(db: AsyncSession, user_id: str) -> AgentProfile:
    profile = await db.get(AgentProfile, user_id)
    if profile is None:
        profile = AgentProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


async def update_profile(db: AsyncSession, user_id: str, changes: dict) -> AgentProfile:
    profile = await get_or_create_profile(db, user_id)
    for key, value in changes.items():
        setattr(profile, key, value)
    await db.flush()
    return profile


async def list_published_agents(db: AsyncSession) -> list[tuple[User, AgentProfile]]:
    rows = await db.execute(
        select(User, AgentProfile)
        .join(AgentProfile, AgentProfile.user_id == User.id)
        .where(
            AgentProfile.published.is_(True),
            User.is_active.is_(True),
            User.role.in_(STAFF_ROLES),
        )
        .order_by(User.first_name)
    )
    return [(u, p) for u, p in rows.all()]
