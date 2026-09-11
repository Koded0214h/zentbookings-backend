from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import EmailStr, Field, field_serializer

from app.schemas.common import CamelModel

ConversationStatus = Literal["OPEN", "CLOSED"]
SenderRole = Literal["guest", "staff"]


def _iso_z(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ConversationCreate(CamelModel):
    property_id: int
    guest_name: str | None = Field(default=None, max_length=200)
    guest_email: EmailStr | None = None
    guest_phone: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=1, max_length=4000)


class MessageCreate(CamelModel):
    body: str = Field(min_length=1, max_length=4000)
    guest_token: str | None = None


class MessageOut(CamelModel):
    id: str
    conversation_id: str
    sender_role: SenderRole
    sender_user_id: str | None = None
    body: str
    flagged: bool
    flag_reason: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at", when_used="json")
    def _ser_created(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class ConversationOut(CamelModel):
    id: str
    property_id: int
    user_id: str | None = None
    guest_name: str
    guest_email: EmailStr
    guest_phone: str | None = None
    status: ConversationStatus
    last_message_at: datetime | None = None
    created_at: datetime | None = None

    @field_serializer("last_message_at", "created_at", when_used="json")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class ConversationCreateResponse(CamelModel):
    conversation: ConversationOut
    message: MessageOut
    # only present when the creator is an unauthenticated guest — the key to
    # read/reply on this thread without an account; never shown again.
    guest_token: str | None = None


class ConversationListResponse(CamelModel):
    conversations: list[ConversationOut]
    total: int
    page: int
    limit: int
    total_pages: int


class MessageListResponse(CamelModel):
    messages: list[MessageOut]
    total: int
    page: int
    limit: int
    total_pages: int
