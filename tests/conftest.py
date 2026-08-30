from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.ratelimit import limiter
from app.main import app
from app.services.email import get_email_sender
from app.services.email.base import EmailSender


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class CapturingEmailSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def email_sender():
    return CapturingEmailSender()


@pytest_asyncio.fixture
async def client(session_factory, email_sender):
    async def _get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_email_sender] = lambda: email_sender

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def registered_user(client):
    payload = {
        "firstName": "Amara",
        "lastName": "Adeyemi",
        "email": "amara@example.com",
        "password": "SecurePass123",
    }
    res = await client.post("/api/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return {"payload": payload, "body": res.json()}
