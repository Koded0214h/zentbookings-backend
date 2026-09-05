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
    from app.core.observability import metrics

    limiter.reset()
    metrics.reset()
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


def _extract_otp(email_sender, to: str) -> str:
    import re

    for sent in reversed(email_sender.sent):
        if sent["to"] == to:
            match = re.search(r"\b(\d{6})\b", sent["text"] or sent["html"])
            if match:
                return match.group(1)
    raise AssertionError(f"no OTP email found for {to}")


async def _register(client, email_sender, email: str, first="T", last="U") -> dict:
    """Register + verify-otp, returning the final {token, user} body."""
    res = await client.post(
        "/api/auth/register",
        json={"firstName": first, "lastName": last, "email": email, "password": "SecurePass123"},
    )
    assert res.status_code == 201, res.text
    assert "token" not in res.json()  # unverified: no session yet

    code = _extract_otp(email_sender, email)
    verified = await client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert verified.status_code == 200, verified.text
    return verified.json()


@pytest_asyncio.fixture
async def registered_user(client, email_sender):
    payload = {
        "firstName": "Amara",
        "lastName": "Adeyemi",
        "email": "amara@example.com",
        "password": "SecurePass123",
    }
    body = await _register(
        client, email_sender, payload["email"], payload["firstName"], payload["lastName"]
    )
    return {"payload": payload, "body": body}


@pytest_asyncio.fixture
async def admin_auth(client, email_sender, session_factory):
    from sqlalchemy import select

    from app.models.user import User

    body = await _register(client, email_sender, "admin@example.com", "Admin", "User")
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "admin@example.com"))
        ).scalar_one()
        user.role = "admin"
        await db.commit()
    return {"Authorization": f"Bearer {body['token']}"}


async def _set_role(session_factory, email: str, role: str) -> str:
    from sqlalchemy import select

    from app.models.user import User

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.role = role
        await db.commit()
        return user.id


@pytest_asyncio.fixture
async def agent_auth(client, email_sender, session_factory):
    body = await _register(client, email_sender, "agent@example.com", "Ada", "Agent")
    agent_id = await _set_role(session_factory, "agent@example.com", "agent")
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "id": agent_id}


def sample_property(**overrides) -> dict:
    body = {
        "title": "The Obsidian Loft",
        "location": "Victoria Island, Lagos",
        "image": "https://cdn.zentbookings.com/images/prop-1.jpg",
        "gallery": ["https://cdn.zentbookings.com/images/prop-1-1.jpg"],
        "beds": 3,
        "baths": 3,
        "sqft": 2800,
        "price": 850000,
        "period": "Per Month",
        "yearBuilt": 2023,
        "amenities": ["Smart Home System", "Private Pool", "24/7 Security"],
        "description": "Where Precision Meets Panorama",
        "fullDescription": "Full property writeup with lots of detail.",
        "dotColor": "#FFE501",
        "category": "Rent",
    }
    body.update(overrides)
    return body


def next_open_slot(days_ahead: int = 3, hhmm: str = "10:00") -> tuple[str, str]:
    """A weekday date + time valid under the default schedule (Mon-Fri 10-17, >=12h notice)."""
    from datetime import date, timedelta

    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() >= 5:  # push Sat/Sun to Monday
        d += timedelta(days=1)
    return d.isoformat(), hhmm


@pytest_asyncio.fixture
async def booking_property(client, admin_auth):
    res = await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest_asyncio.fixture
async def seeded_properties(session_factory):
    """Insert a deterministic mix straight into the DB for list/filter tests."""
    from app.models.property import Property

    rows = []
    for i in range(1, 26):  # 25 rows
        rent = i % 2 == 0
        rows.append(
            Property(
                title=f"Unit {i}",
                location="Lekki Phase 1, Lagos" if i % 3 == 0 else "Ikoyi, Lagos",
                image=f"https://cdn.zentbookings.com/p/{i}.jpg",
                gallery=[],
                beds=(i % 4) + 1,
                baths=(i % 3) + 1,
                sqft=1000 + i * 50,
                price=(100_000 * i) if rent else (20_000 * i),
                period="Per Month" if rent else "Per Night",
                type="Monthly" if rent else "Nightly",
                year_built=2016 + (i % 8),
                amenities=["Gym"] if i % 2 else ["Pool", "Gym"],
                description=f"Desc {i}",
                full_description=f"Full desc {i}",
                dot_color="#111111",
                category="Rent" if rent else "Shortlet",
            )
        )
    async with session_factory() as db:
        db.add_all(rows)
        await db.commit()
    return len(rows)
