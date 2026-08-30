from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Runtime -------------------------------------------------------------
    PROD: bool = False
    API_PREFIX: str = "/api"

    # --- Database ----------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://zent:zent@localhost:5432/zent"

    # --- Auth / JWT ------------------------------------------------------------
    SECRET_KEY: str = _DEV_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = 12  # PRD 6.2 requires >= 10
    # PRD 6.2 "refresh on activity": once a token is this far through its life, an
    # authenticated response carries a fresh one in the X-Renewed-Token header.
    TOKEN_RENEW_THRESHOLD_RATIO: float = 0.5

    # --- Rate limiting (per client IP, sliding window) ---------------------
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT: str = "10/60"           # 10 attempts / 60s
    REGISTER_RATE_LIMIT: str = "5/60"
    FORGOT_PASSWORD_RATE_LIMIT: str = "5/300"

    # --- Background maintenance ---------------------------------------------
    CLEANUP_ENABLED: bool = True
    CLEANUP_INTERVAL_SECONDS: int = 3600

    # --- Frontend / CORS -----------------------------------------------------
    FRONTEND_BASE_URL: str = "https://zentbookings.com"
    CORS_ORIGINS: str = (
        "https://zentbookings.com,https://www.zentbookings.com,"
        "http://localhost:5173,http://localhost:3000"
    )
    ALLOWED_OAUTH_REDIRECT_HOSTS: str = (
        "zentbookings.com,www.zentbookings.com,localhost,127.0.0.1"
    )

    # --- Token TTLs (seconds) ---------------------------------------------------
    OAUTH_STATE_TTL_SECONDS: int = 600
    EMAIL_VERIFY_TTL_SECONDS: int = 60 * 60 * 24  # 24h
    PASSWORD_RESET_TTL_SECONDS: int = 60 * 60  # 1h

    # --- Google OAuth ------------------------------------------------------------
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    # Backend callback registered in GCP, e.g. https://api.zentbookings.com/api/auth/google/callback
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    # Google `prompt` param. "select_account consent" forces the consent (branding)
    # screen every time — handy while verifying branding. Use "select_account" in prod.
    GOOGLE_OAUTH_PROMPT: str = "select_account consent"

    # --- Apple OAuth -----------------------------------------------------------
    APPLE_CLIENT_ID: str | None = None  # Services ID
    APPLE_TEAM_ID: str | None = None
    APPLE_KEY_ID: str | None = None
    APPLE_PRIVATE_KEY: str | None = None  # contents of the .p8 file
    APPLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/apple/callback"

    # --- SMTP (used when PROD is true) --------------------------------------
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "Zent <no-reply@zentbookings.com>"
    # "starttls" -> port 587, "ssl" -> port 465 (implicit TLS), "none" -> plaintext
    SMTP_SECURITY: str = "starttls"

    # --- Derived helpers -----------------------------------------------------
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_oauth_redirect_hosts(self) -> set[str]:
        raw = self.ALLOWED_OAUTH_REDIRECT_HOSTS.split(",")
        return {h.strip().lower() for h in raw if h.strip()}

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def apple_configured(self) -> bool:
        return bool(
            self.APPLE_CLIENT_ID
            and self.APPLE_TEAM_ID
            and self.APPLE_KEY_ID
            and self.APPLE_PRIVATE_KEY
        )

    @model_validator(mode="after")
    def _guard_prod(self) -> Settings:
        if self.PROD:
            if self.SECRET_KEY == _DEV_SECRET:
                raise ValueError("SECRET_KEY must be set to a strong value when PROD=true")
            if not self.SMTP_HOST:
                raise ValueError("SMTP_HOST is required when PROD=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
