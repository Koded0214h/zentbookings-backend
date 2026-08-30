from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings


# --- Password hashing -----------------------------------------------------------
def _prehash(password: str) -> bytes:
    """SHA-256 -> base64 so bcrypt's 72-byte input limit never truncates a password."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode())
    except (ValueError, TypeError):
        return False


# --- JWT access tokens --------------------------------------------------------
def create_access_token(subject: str, *, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS))
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_hex(16),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on any problem (expiry, signature, malformed)."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# --- Opaque tokens (email verification, password reset) ----------------------
def generate_url_token() -> tuple[str, str]:
    """Return (raw_token_for_url, sha256_hex_for_storage)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_url_token(raw)


def hash_url_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
