from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.messaging import Conversation, Message
from app.models.property import Property
from app.models.user import User, _utcnow
from app.services import moderation


class ConversationNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "conversation_not_found", "Conversation not found.")


class ConversationForbidden(AppError):
    def __init__(self) -> None:
        super().__init__(403, "forbidden", "You cannot access this conversation.")


@dataclass(slots=True)
class ConversationFilters:
    property_id: int | None = None
    property_ids: list[int] | None = None
    status: str | None = None


async def open_conversation(
    db: AsyncSession,
    *,
    property_id: int,
    user: User | None,
    guest_name: str | None,
    guest_email: str | None,
    guest_phone: str | None,
) -> Conversation:
    prop = await db.get(Property, property_id)
    if prop is None or prop.deleted_at is not None:
        raise AppError(404, "property_not_found", "Property not found.")

    name = guest_name or (user.full_name if user else None)
    email = guest_email or (user.email if user else None)
    if not name or not email:
        raise AppError(
            422, "validation_error", "Missing required guest fields: guestName, guestEmail"
        )
    email = str(email).lower()

    existing = await db.scalar(
        select(Conversation).where(
            Conversation.property_id == property_id,
            Conversation.status == "OPEN",
            Conversation.user_id == user.id
            if user
            else func.lower(Conversation.guest_email) == email,
        )
    )
    if existing is not None:
        return existing

    conversation = Conversation(
        property_id=property_id,
        user_id=user.id if user else None,
        guest_name=name,
        guest_email=email,
        guest_phone=guest_phone,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def post_message(
    db: AsyncSession,
    conversation: Conversation,
    *,
    sender_role: str,
    sender_user_id: str | None,
    body: str,
) -> Message:
    flag_reason = moderation.check(body)
    message = Message(
        conversation_id=conversation.id,
        sender_role=sender_role,
        sender_user_id=sender_user_id,
        body=body,
        flagged=flag_reason is not None,
        flag_reason=flag_reason,
    )
    db.add(message)
    conversation.last_message_at = _utcnow()
    await db.flush()
    return message


async def get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFound()
    return conversation


async def get_conversation_by_guest_token(db: AsyncSession, token: str) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(Conversation.guest_token == token)
    )
    if conversation is None:
        raise ConversationNotFound()
    return conversation


def can_access(
    conversation: Conversation,
    *,
    user: User | None,
    staff_property_ids: list[int] | None,
    is_admin: bool,
    guest_token: str | None,
) -> bool:
    if guest_token and conversation.guest_token == guest_token:
        return True
    if user is None:
        return False
    if conversation.user_id == user.id:
        return True
    if is_admin:
        return True
    if staff_property_ids is not None and conversation.property_id in staff_property_ids:
        return True
    return False


async def list_conversations(
    db: AsyncSession,
    *,
    filters: ConversationFilters,
    owner: User | None,
    staff: bool,
    page: int,
    limit: int,
) -> tuple[list[Conversation], int, int]:
    stmt = select(Conversation)
    count_stmt = select(func.count()).select_from(Conversation)
    if not staff:
        uid = owner.id if owner else "\x00none"
        stmt = stmt.where(Conversation.user_id == uid)
        count_stmt = count_stmt.where(Conversation.user_id == uid)
    if filters.property_id is not None:
        stmt = stmt.where(Conversation.property_id == filters.property_id)
        count_stmt = count_stmt.where(Conversation.property_id == filters.property_id)
    if filters.property_ids is not None:
        stmt = stmt.where(Conversation.property_id.in_(filters.property_ids or [-1]))
        count_stmt = count_stmt.where(Conversation.property_id.in_(filters.property_ids or [-1]))
    if filters.status:
        stmt = stmt.where(Conversation.status == filters.status.upper())
        count_stmt = count_stmt.where(Conversation.status == filters.status.upper())

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(Conversation.updated_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0


async def list_messages(
    db: AsyncSession, conversation_id: str, *, page: int, limit: int
) -> tuple[list[Message], int, int]:
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        or 0
    )
    rows = (
        (
            await db.execute(
                stmt.order_by(Message.created_at.asc()).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total, ceil(total / limit) if limit else 0
