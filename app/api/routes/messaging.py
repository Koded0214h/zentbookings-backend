from __future__ import annotations

import asyncio
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import decode_access_token
from app.models.messaging import Conversation
from app.models.user import User
from app.schemas.messaging import (
    ConversationCreate,
    ConversationCreateResponse,
    ConversationListResponse,
    ConversationOut,
    MessageCreate,
    MessageListResponse,
    MessageOut,
)
from app.services import messaging_service, staff_service
from app.services.auth_service import is_token_revoked
from app.services.messaging_service import ConversationFilters, ConversationForbidden
from app.services.pubsub import get_broker

router = APIRouter(tags=["messaging"])

_create_limit = [
    Depends(rate_limit("conversation_create", settings.CONVERSATION_CREATE_RATE_LIMIT))
]
_send_limit = [Depends(rate_limit("message_send", settings.MESSAGE_SEND_RATE_LIMIT))]


def _is_staff(user: User | None) -> bool:
    return bool(user and user.role in ("admin", "agent"))


async def _staff_scope(db: AsyncSession, user: User | None) -> tuple[list[int] | None, bool]:
    """(assigned_property_ids, is_admin) for the given staff user, else (None, False)."""
    if user is None or user.role not in ("admin", "agent"):
        return None, False
    if user.role == "admin":
        return None, True
    return await staff_service.assigned_property_ids(db, user.id), False


async def _load_and_authorize(
    db: AsyncSession, conversation_id: str, user: User | None, guest_token: str | None
) -> Conversation:
    conversation = await messaging_service.get_conversation(db, conversation_id)
    staff_ids, is_admin = await _staff_scope(db, user)
    if not messaging_service.can_access(
        conversation,
        user=user,
        staff_property_ids=staff_ids,
        is_admin=is_admin,
        guest_token=guest_token,
    ):
        raise ConversationForbidden()
    return conversation


@router.post(
    "/conversations",
    response_model=ConversationCreateResponse,
    status_code=201,
    dependencies=_create_limit,
)
async def create_conversation(
    payload: ConversationCreate, db: DbSession, user: OptionalUser
) -> ConversationCreateResponse:
    conversation = await messaging_service.open_conversation(
        db,
        property_id=payload.property_id,
        user=user,
        guest_name=payload.guest_name,
        guest_email=payload.guest_email,
        guest_phone=payload.guest_phone,
    )
    message = await messaging_service.post_message(
        db,
        conversation,
        sender_role="guest",
        sender_user_id=user.id if user else None,
        body=payload.message,
    )
    await db.commit()

    broker = await get_broker()
    await broker.publish(
        f"conv:{conversation.id}",
        MessageOut.model_validate(message).model_dump(mode="json", by_alias=True),
    )

    return ConversationCreateResponse(
        conversation=ConversationOut.model_validate(conversation),
        message=MessageOut.model_validate(message),
        guest_token=None if user else conversation.guest_token,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    property_id: Annotated[int | None, Query(alias="propertyId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> ConversationListResponse:
    staff_ids, is_admin = await _staff_scope(db, user)
    staff = _is_staff(user)
    rows, total, pages = await messaging_service.list_conversations(
        db,
        filters=ConversationFilters(
            property_id=property_id,
            property_ids=None if is_admin else staff_ids,
            status=status_,
        ),
        owner=user,
        staff=staff,
        page=page,
        limit=limit,
    )
    return ConversationListResponse(
        conversations=[ConversationOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    db: DbSession,
    user: OptionalUser,
    guest_token: Annotated[str | None, Query(alias="guestToken")] = None,
) -> ConversationOut:
    conversation = await _load_and_authorize(db, conversation_id, user, guest_token)
    return ConversationOut.model_validate(conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
async def get_messages(
    conversation_id: str,
    db: DbSession,
    user: OptionalUser,
    guest_token: Annotated[str | None, Query(alias="guestToken")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessageListResponse:
    await _load_and_authorize(db, conversation_id, user, guest_token)
    rows, total, pages = await messaging_service.list_messages(
        db, conversation_id, page=page, limit=limit
    )
    return MessageListResponse(
        messages=[MessageOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=pages,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=201,
    dependencies=_send_limit,
)
async def send_message(
    conversation_id: str, payload: MessageCreate, db: DbSession, user: OptionalUser
) -> MessageOut:
    conversation = await _load_and_authorize(db, conversation_id, user, payload.guest_token)
    sender_role = "staff" if _is_staff(user) else "guest"
    message = await messaging_service.post_message(
        db,
        conversation,
        sender_role=sender_role,
        sender_user_id=user.id if user else None,
        body=payload.body,
    )
    await db.commit()

    broker = await get_broker()
    await broker.publish(
        f"conv:{conversation.id}",
        MessageOut.model_validate(message).model_dump(mode="json", by_alias=True),
    )
    return MessageOut.model_validate(message)


async def _ws_user(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    jti, sub = payload.get("jti"), payload.get("sub")
    if not jti or not sub or await is_token_revoked(db, jti):
        return None
    user = await db.get(User, sub)
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/conversations/{conversation_id}")
async def ws_conversation(websocket: WebSocket, conversation_id: str, db: DbSession) -> None:
    token = websocket.query_params.get("token")
    guest_token = websocket.query_params.get("guestToken")

    user = await _ws_user(db, token)
    if token and user is None:
        await websocket.close(code=4401)
        return

    try:
        conversation = await messaging_service.get_conversation(db, conversation_id)
    except Exception:
        await websocket.close(code=4404)
        return

    staff_ids, is_admin = await _staff_scope(db, user)
    if not messaging_service.can_access(
        conversation,
        user=user,
        staff_property_ids=staff_ids,
        is_admin=is_admin,
        guest_token=guest_token,
    ):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    broker = await get_broker()
    channel = f"conv:{conversation_id}"

    async def _relay(queue: asyncio.Queue) -> None:
        while True:
            item = await queue.get()
            await websocket.send_json(item)

    async with broker.subscribe(channel) as queue:
        relay_task = asyncio.create_task(_relay(queue))
        try:
            while True:
                data = await websocket.receive_json()
                body = str((data or {}).get("body", "")).strip()
                if not body:
                    continue
                sender_role = "staff" if _is_staff(user) else "guest"
                message = await messaging_service.post_message(
                    db,
                    conversation,
                    sender_role=sender_role,
                    sender_user_id=user.id if user else None,
                    body=body,
                )
                await db.commit()
                await broker.publish(
                    channel,
                    MessageOut.model_validate(message).model_dump(mode="json", by_alias=True),
                )
        except WebSocketDisconnect:
            pass
        finally:
            relay_task.cancel()
