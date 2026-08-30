from __future__ import annotations

import time
from typing import Annotated

import jwt
from fastapi import Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AppError
from app.core.security import create_access_token, decode_access_token
from app.models.user import User
from app.services.auth_service import is_token_revoked

_bearer = HTTPBearer(auto_error=True, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


class _Unauthorized(AppError):
    def __init__(self, message: str = "Not authenticated.") -> None:
        super().__init__(401, "unauthorized", message)


def _maybe_renew(response: Response, claims: dict) -> None:
    """PRD 6.2 sliding refresh: hand back a fresh token once past the threshold."""
    iat, exp = claims.get("iat"), claims.get("exp")
    if not iat or not exp:
        return
    lifetime = exp - iat
    if lifetime <= 0:
        return
    elapsed = time.time() - iat
    if elapsed / lifetime >= settings.TOKEN_RENEW_THRESHOLD_RATIO:
        response.headers["X-Renewed-Token"] = create_access_token(claims["sub"])


async def get_current_user(
    db: DbSession,
    response: Response,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> User:
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _Unauthorized("Invalid or expired session.") from None

    jti = payload.get("jti")
    sub = payload.get("sub")
    if not jti or not sub:
        raise _Unauthorized("Invalid session token.")
    if await is_token_revoked(db, jti):
        raise _Unauthorized("Session has been signed out.")

    user = await db.get(User, sub)
    if user is None or not user.is_active:
        raise _Unauthorized("Account is unavailable.")

    _maybe_renew(response, payload)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_token_claims(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    try:
        return decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _Unauthorized("Invalid or expired session.") from None


TokenClaims = Annotated[dict, Depends(get_token_claims)]


def require_roles(*roles: str):
    async def _guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have access to this resource.")
        return user

    return _guard
