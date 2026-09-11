from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin, _utcnow, gen_id

CONVERSATION_STATUSES = ("OPEN", "CLOSED")
SENDER_ROLES = ("guest", "staff")


def _guest_token() -> str:
    return secrets.token_urlsafe(24)


class Conversation(TimestampMixin, Base):
    """One thread per (property, guest) pair — mirrors the Airbnb-style inbox."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_property_guest", "property_id", "guest_email"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("cnv"))
    property_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    guest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    guest_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    guest_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # lets an unauthenticated guest read/post without an account, same spirit
    # as a booking confirmation code — never exposed to anyone else.
    guest_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_guest_token, nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), default="OPEN", nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("msg"))
    conversation_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_role: Mapped[str] = mapped_column(String(10), nullable=False)  # guest | staff
    sender_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
