from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import EmailStr, Field, field_serializer

from app.schemas.common import CamelModel

Role = Literal["user", "agent", "admin"]
StaffRole = Literal["agent", "admin"]


def _iso_z(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Admin: users -------------------------------------------------------------
class AdminUserOut(CamelModel):
    id: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    role: Role
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    last_login_method: str | None = None
    last_seen_at: datetime | None = None
    created_at: datetime | None = None

    @field_serializer(
        "last_login_at", "last_seen_at", "created_at", when_used="json"
    )
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class AdminUserListResponse(CamelModel):
    users: list[AdminUserOut]
    total: int
    page: int
    limit: int
    total_pages: int


class RoleUpdate(CamelModel):
    role: Role


class StatusUpdate(CamelModel):
    is_active: bool


class AgentInvite(CamelModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: StaffRole = "agent"


# --- Attendance -------------------------------------------------------------
class ClockInRequest(CamelModel):
    source: Literal["web", "mobile", "api"] = "web"


class AttendanceOut(CamelModel):
    id: str
    user_id: str
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    duration_minutes: int | None = None
    source: str
    ip: str | None = None
    auto_closed: bool
    note: str | None = None

    @field_serializer("clock_in_at", "clock_out_at", when_used="json")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class AttendanceListResponse(CamelModel):
    records: list[AttendanceOut]
    total: int
    page: int
    limit: int
    total_pages: int


class AttendanceStatusOut(CamelModel):
    clocked_in: bool
    since: datetime | None = None
    today_minutes: int

    @field_serializer("since", when_used="json")
    def _ser_since(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class AttendanceEdit(CamelModel):
    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class AttendanceSummaryRow(CamelModel):
    user_id: str
    sessions: int
    total_minutes: int


class AttendanceSummaryResponse(CamelModel):
    from_: str = Field(alias="from")
    to: str
    rows: list[AttendanceSummaryRow]


# --- Audit log ------------------------------------------------------------
class AuditEntryOut(CamelModel):
    id: str
    actor_user_id: str | None = None
    action: str
    target_type: str
    target_id: str
    metadata: dict
    ip: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at", when_used="json")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class AuditListResponse(CamelModel):
    entries: list[AuditEntryOut]
    total: int
    page: int
    limit: int
    total_pages: int


# --- Agent assignment ---------------------------------------------------
class AssignAgentRequest(CamelModel):
    agent_id: str


class PropertyAgentsOut(CamelModel):
    property_id: int
    agent_ids: list[str]


# --- Agent public profile --------------------------------------------------
class AgentProfileUpdate(CamelModel):
    title: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=4000)
    phone: str | None = Field(default=None, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=400)
    headshot_url: str | None = Field(default=None, max_length=1024)
    headshot_public_id: str | None = Field(default=None, max_length=255)
    published: bool | None = None


class AgentProfileOut(CamelModel):
    user_id: str
    title: str | None = None
    bio: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    headshot_url: str | None = None
    published: bool


class PublicAgentOut(CamelModel):
    id: str
    full_name: str | None = None
    avatar_url: str | None = None
    title: str | None = None
    bio: str | None = None
    linkedin_url: str | None = None
    headshot_url: str | None = None


class PublicAgentListResponse(CamelModel):
    agents: list[PublicAgentOut]
