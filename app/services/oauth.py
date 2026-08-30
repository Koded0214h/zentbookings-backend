from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import OAuthFailed
from app.models.user import OAuthState

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"


# --- PKCE + redirect helpers ------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def validate_frontend_redirect(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise OAuthFailed("Invalid redirect_uri.")
    if parsed.hostname.lower() not in settings.allowed_oauth_redirect_hosts:
        raise OAuthFailed("redirect_uri host is not allowed.")
    return redirect_uri


def append_query(url: str, **params: str) -> str:
    sep = "&" if urlparse(url).query else "?"
    return f"{url}{sep}{urlencode(params)}"


async def create_state(
    db: AsyncSession, *, provider: str, redirect_uri: str
) -> tuple[str, str]:
    """Persist a flow and return (state, code_challenge)."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state=state,
            provider=provider,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.OAUTH_STATE_TTL_SECONDS),
        )
    )
    await db.flush()
    return state, challenge


async def consume_state(db: AsyncSession, *, provider: str, state: str) -> OAuthState:
    row = await db.get(OAuthState, state)
    if row is None or row.provider != provider:
        raise OAuthFailed("Unknown or expired sign-in session.")
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    await db.delete(row)
    await db.flush()
    if expires_at < datetime.now(UTC):
        raise OAuthFailed("Sign-in session expired. Please try again.")
    return row


# --- Google ---------------------------------------------------------------
def google_authorize_url(*, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": settings.GOOGLE_OAUTH_PROMPT,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def google_fetch_profile(*, code: str, code_verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            },
        )
        if token_res.status_code != 200:
            raise OAuthFailed("Could not complete Google sign-in.")
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise OAuthFailed("Could not complete Google sign-in.")

        info_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_res.status_code != 200:
            raise OAuthFailed("Could not read your Google profile.")

    data = info_res.json()
    return {
        "account_id": data["sub"],
        "email": data.get("email"),
        "first_name": data.get("given_name"),
        "last_name": data.get("family_name"),
        "avatar_url": data.get("picture"),
    }


# --- Apple --------------------------------------------------------------------
def _apple_client_secret() -> str:
    now = int(time.time())
    headers = {"kid": settings.APPLE_KEY_ID, "alg": "ES256"}
    payload = {
        "iss": settings.APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 3600,
        "aud": APPLE_ISSUER,
        "sub": settings.APPLE_CLIENT_ID,
    }
    return jwt.encode(payload, settings.APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers)


def apple_authorize_url(*, state: str) -> str:
    params = {
        "client_id": settings.APPLE_CLIENT_ID,
        "redirect_uri": settings.APPLE_REDIRECT_URI,
        "response_type": "code",
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
    }
    return f"{APPLE_AUTH_URL}?{urlencode(params)}"


def _verify_apple_id_token(id_token: str) -> dict:
    jwk_client = jwt.PyJWKClient(APPLE_JWKS_URL)
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.APPLE_CLIENT_ID,
        issuer=APPLE_ISSUER,
    )


async def apple_fetch_profile(*, code: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        token_res = await client.post(
            APPLE_TOKEN_URL,
            data={
                "client_id": settings.APPLE_CLIENT_ID,
                "client_secret": _apple_client_secret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.APPLE_REDIRECT_URI,
            },
        )
    if token_res.status_code != 200:
        raise OAuthFailed("Could not complete Apple sign-in.")
    id_token = token_res.json().get("id_token")
    if not id_token:
        raise OAuthFailed("Could not complete Apple sign-in.")

    claims = await asyncio.to_thread(_verify_apple_id_token, id_token)
    return {
        "account_id": claims["sub"],
        "email": claims.get("email"),
        "first_name": None,
        "last_name": None,
        "avatar_url": None,
    }
