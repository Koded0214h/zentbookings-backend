from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.user import OAuthState, TokenDenylist
from app.services.maintenance import purge_expired


async def test_purge_expired_removes_only_stale_rows(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                TokenDenylist(jti="expired-1", expires_at=now - timedelta(hours=1)),
                TokenDenylist(jti="live-1", expires_at=now + timedelta(hours=1)),
                OAuthState(
                    state="expired-state",
                    provider="google",
                    code_verifier="v",
                    redirect_uri="https://zentbookings.com/",
                    expires_at=now - timedelta(minutes=5),
                ),
                OAuthState(
                    state="live-state",
                    provider="google",
                    code_verifier="v",
                    redirect_uri="https://zentbookings.com/",
                    expires_at=now + timedelta(minutes=5),
                ),
            ]
        )
        await db.commit()

    async with session_factory() as db:
        counts = await purge_expired(db, now=now)

    assert counts["token_denylist"] == 1
    assert counts["oauth_states"] == 1

    async with session_factory() as db:
        deny = (await db.execute(select(func.count()).select_from(TokenDenylist))).scalar()
        states = (await db.execute(select(func.count()).select_from(OAuthState))).scalar()
    assert deny == 1
    assert states == 1


async def test_purge_expired_noop_when_all_live(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(TokenDenylist(jti="live", expires_at=now + timedelta(days=1)))
        await db.commit()

    async with session_factory() as db:
        counts = await purge_expired(db, now=now)
    assert sum(counts.values()) == 0
