from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.core.exceptions import AppError
from app.models.staff import AgentProfile
from app.models.user import User
from app.schemas.staff import PublicAgentListResponse, PublicAgentOut
from app.services import staff_service

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_public(user: User, profile: AgentProfile) -> PublicAgentOut:
    return PublicAgentOut(
        id=user.id,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        title=profile.title,
        bio=profile.bio,
        linkedin_url=profile.linkedin_url,
        headshot_url=profile.headshot_url,
    )


@router.get("", response_model=PublicAgentListResponse)
async def list_agents(db: DbSession) -> PublicAgentListResponse:
    pairs = await staff_service.list_published_agents(db)
    return PublicAgentListResponse(agents=[_to_public(u, p) for u, p in pairs])


@router.get("/{agent_id}", response_model=PublicAgentOut)
async def get_agent(agent_id: str, db: DbSession) -> PublicAgentOut:
    user = await db.get(User, agent_id)
    profile = await db.get(AgentProfile, agent_id)
    if (
        user is None
        or profile is None
        or not profile.published
        or not user.is_active
        or user.role not in ("agent", "admin")
    ):
        raise AppError(404, "agent_not_found", "Agent not found.")
    return _to_public(user, profile)
