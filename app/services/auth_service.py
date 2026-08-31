from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import EmailAlreadyExists, InvalidCredentials, InvalidToken
from app.core.security import (
    generate_url_token,
    hash_password,
    hash_url_token,
    verify_password,
)
from app.models.user import (
    EmailVerificationToken,
    OAuthAccount,
    PasswordResetToken,
    TokenDenylist,
    User,
)
from app.schemas.auth import RegisterRequest


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


# --- Users -------------------------------------------------------------------
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == normalize_email(email)))
    return res.scalar_one_or_none()


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    if await get_user_by_email(db, data.email):
        raise EmailAlreadyExists()
    user = User(
        email=normalize_email(data.email),
        hashed_password=hash_password(data.password),
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        is_verified=True,  # auto-confirm on register (PRD open item 9.2, decision: auto)
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    if not user or not user.hashed_password:
        raise InvalidCredentials()
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentials()
    if not user.is_active:
        raise InvalidCredentials()
    return user


async def upsert_oauth_user(
    db: AsyncSession,
    *,
    provider: str,
    account_id: str,
    email: str | None,
    first_name: str | None = None,
    last_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    res = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_account_id == account_id,
        )
    )
    account = res.scalar_one_or_none()
    if account is not None:
        user = await db.get(User, account.user_id)
        if user and avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
        return user

    user = await get_user_by_email(db, email) if email else None
    if user is None:
        if not email:
            raise InvalidToken("The identity provider did not return an email address.")
        user = User(
            email=normalize_email(email),
            first_name=first_name,
            last_name=last_name,
            avatar_url=avatar_url,
            is_verified=True,  # provider-verified identity
        )
        db.add(user)
        await db.flush()

    db.add(
        OAuthAccount(user_id=user.id, provider=provider, provider_account_id=account_id)
    )
    await db.flush()
    return user


# --- Email verification ----------------------------------------------------
async def issue_email_verification_token(db: AsyncSession, user: User) -> str:
    raw, token_hash = generate_url_token()
    db.add(
        EmailVerificationToken(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=_utcnow() + timedelta(seconds=settings.EMAIL_VERIFY_TTL_SECONDS),
        )
    )
    await db.flush()
    return raw


async def confirm_email_verification(db: AsyncSession, raw_token: str) -> User:
    row = await db.get(EmailVerificationToken, hash_url_token(raw_token))
    if row is None or row.used_at is not None or _aware(row.expires_at) < _utcnow():
        raise InvalidToken()
    user = await db.get(User, row.user_id)
    if user is None:
        raise InvalidToken()
    user.is_verified = True
    row.used_at = _utcnow()
    await db.flush()
    return user


# --- Password reset --------------------------------------------------------
async def issue_password_reset_token(db: AsyncSession, user: User) -> str:
    raw, token_hash = generate_url_token()
    db.add(
        PasswordResetToken(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=_utcnow() + timedelta(seconds=settings.PASSWORD_RESET_TTL_SECONDS),
        )
    )
    await db.flush()
    return raw


async def reset_password(db: AsyncSession, raw_token: str, new_password: str) -> User:
    row = await db.get(PasswordResetToken, hash_url_token(raw_token))
    if row is None or row.used_at is not None or _aware(row.expires_at) < _utcnow():
        raise InvalidToken()
    user = await db.get(User, row.user_id)
    if user is None:
        raise InvalidToken()
    user.hashed_password = hash_password(new_password)
    row.used_at = _utcnow()
    await db.flush()
    return user


# --- JWT denylist (logout) -----------------------------------------------
async def revoke_token(db: AsyncSession, jti: str, expires_at: datetime) -> None:
    if await db.get(TokenDenylist, jti) is None:
        db.add(TokenDenylist(jti=jti, expires_at=expires_at))
        await db.flush()


async def is_token_revoked(db: AsyncSession, jti: str) -> bool:
    return await db.get(TokenDenylist, jti) is not None


# --- Login & presence (Module 4.5) ---------------------------------------
async def record_login(
    db: AsyncSession, user: User, *, method: str, ip: str | None
) -> None:
    now = _utcnow()
    user.last_login_at = now
    user.last_login_method = method
    user.last_login_ip = ip
    user.last_seen_at = now
    await db.flush()


async def touch_last_seen(db: AsyncSession, user: User) -> None:
    """Bump last_seen_at at most once per throttle window, on the request session.

    Runs in the auth dependency (before the handler), so committing here is safe
    and independent of whether the handler itself commits.
    """
    last = user.last_seen_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if (_utcnow() - last).total_seconds() < settings.LAST_SEEN_THROTTLE_SECONDS:
            return
    try:
        now = _utcnow()
        await db.execute(update(User).where(User.id == user.id).values(last_seen_at=now))
        await db.commit()
        user.last_seen_at = now
    except Exception:  # never break a request over presence tracking
        await db.rollback()
