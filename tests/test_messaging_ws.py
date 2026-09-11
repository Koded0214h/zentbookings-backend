from __future__ import annotations

import asyncio

import pytest
from conftest import sample_property
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.core.database import Base, get_db
from app.main import app
from app.models.user import EmailOtp, User
from app.services.email import get_email_sender
from app.services.email.base import EmailSender
from app.services.pubsub import reset_broker_for_tests


class _NullSender(EmailSender):
    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        return None


@pytest.fixture
def ws_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_tables(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_email_sender] = lambda: _NullSender()
    asyncio.run(reset_broker_for_tests())

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


async def _create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _verify_and_promote_to_admin(email: str) -> None:
    # OTP verification normally reads the code from the outbound email, but
    # the sender is swapped for _NullSender here — go straight to the DB
    # instead of round-tripping through /auth/verify-otp.
    gen = app.dependency_overrides[get_db]()
    db = await gen.__anext__()
    try:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.is_verified = True
        user.role = "admin"
        await db.execute(EmailOtp.__table__.delete().where(EmailOtp.user_id == user.id))
        await db.commit()
    finally:
        await gen.aclose()


def _make_property(ws_client: TestClient) -> int:
    email = "wsadmin@example.com"
    register = ws_client.post(
        "/api/auth/register",
        json={
            "firstName": "Admin",
            "lastName": "User",
            "email": email,
            "password": "SecurePass123",
        },
    )
    assert register.status_code == 201, register.text
    asyncio.run(_verify_and_promote_to_admin(email))

    login = ws_client.post("/api/auth/login", json={"email": email, "password": "SecurePass123"})
    assert login.status_code == 200, login.text
    token = login.json()["token"]

    res = ws_client.post(
        "/api/properties", json=sample_property(), headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_ws_relays_message_to_a_second_connection(ws_client):
    property_id = _make_property(ws_client)
    created = ws_client.post(
        "/api/conversations",
        json={
            "propertyId": property_id,
            "guestName": "Guest",
            "guestEmail": "guest@example.com",
            "guestPhone": "+2348000000000",
            "message": "hello",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["conversation"]["id"]
    token = created.json()["guestToken"]

    with ws_client.websocket_connect(f"/api/ws/conversations/{cid}?guestToken={token}") as ws_a:
        with ws_client.websocket_connect(
            f"/api/ws/conversations/{cid}?guestToken={token}"
        ) as ws_b:
            ws_a.send_json({"body": "are you still there?"})
            received = ws_b.receive_json()
            assert received["body"] == "are you still there?"
            assert received["senderRole"] == "guest"


def test_ws_rejects_wrong_guest_token(ws_client):
    property_id = _make_property(ws_client)
    created = ws_client.post(
        "/api/conversations",
        json={
            "propertyId": property_id,
            "guestName": "Guest",
            "guestEmail": "guest2@example.com",
            "guestPhone": "+2348000000000",
            "message": "hello",
        },
    )
    cid = created.json()["conversation"]["id"]

    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/api/ws/conversations/{cid}?guestToken=wrong"):
            pass
