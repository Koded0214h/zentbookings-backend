# Zent Backend — Module 1: Identity & Access

FastAPI service covering registration, login, sessions, OAuth (Google/Apple),
profile, email verification, and password reset. See
[`MODULE_BREAKDOWN.md`](./MODULE_BREAKDOWN.md) for scope.

## Stack
- FastAPI + Uvicorn
- SQLAlchemy 2 (async) + asyncpg, Alembic migrations
- PyJWT (HS256 access tokens), bcrypt password hashing
- Pluggable email: console/log sender in dev, SMTP when `PROD=true`

## Setup
```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
cp .env.example .env          # fill in secrets (see below)
uv run alembic upgrade head   # or: .venv/bin/python -m alembic upgrade head
uv run uvicorn app.main:app --reload
```
Local Postgres instead of Neon: `docker compose up -d db` and point
`DATABASE_URL` at `postgresql+asyncpg://zent:zent@localhost:5432/zent`.

## Environment
| Var | Notes |
|---|---|
| `PROD` | `true` switches email to SMTP and enforces `SECRET_KEY` / `SMTP_HOST` |
| `DATABASE_URL` | must use `postgresql+asyncpg://`; for Neon append `?ssl=require` (drop `sslmode`/`channel_binding`) |
| `SECRET_KEY` | JWT signing key; `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from GCP → Credentials |
| `GOOGLE_REDIRECT_URI` | backend callback, must match GCP exactly |
| `FRONTEND_BASE_URL` | where OAuth returns the user with `?token=` |
| `ALLOWED_OAUTH_REDIRECT_HOSTS` | allowlist for the `redirect_uri` query param (open-redirect guard) |

## Endpoints (prefix `/api`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register` | – | Create user, returns `{ token, user }` (auto-confirmed). Rate limited. |
| POST | `/auth/login` | – | `{ token, user }`. Rate limited. |
| POST | `/auth/refresh` | Bearer | Swap a valid token for a fresh one; old token revoked (PRD 6.2) |
| POST | `/auth/logout` | Bearer | Revoke current token (JWT denylist) |
| GET | `/auth/me` | Bearer | Current user profile |
| GET | `/auth/verify-email?token=` | – | Confirm email (non-blocking) |
| POST | `/auth/forgot-password` | – | Always 202; emails reset link if account exists. Rate limited. |
| POST | `/auth/reset-password` | – | `{ token, password }`, single-use token |
| GET | `/auth/google?redirect_uri=` | – | Start Google OAuth (PKCE) |
| GET | `/auth/google/callback` | – | Exchange code, redirect to `{redirect_uri}?token=` |
| GET | `/auth/apple` / POST `/auth/apple/callback` | – | Apple OAuth (form_post) |
| GET | `/dev/oauth-landing` | – | Local-only stand-in for the frontend OAuth landing (hidden when `PROD=true`) |

Errors use `{ "error": { "code", "message" } }`; validation errors add `fields[]`.

### Sliding token refresh (PRD 6.2)
Any authenticated response whose token is past `TOKEN_RENEW_THRESHOLD_RATIO`
(default 0.5) of its lifetime carries a fresh token in the `X-Renewed-Token`
response header (exposed via CORS). The frontend can also call `POST /auth/refresh`
explicitly. Access tokens stay 7 days.

### Rate limiting
Per-client-IP sliding window on `/auth/register`, `/auth/login`,
`/auth/forgot-password` (`*_RATE_LIMIT` = `count/seconds`). Over the limit →
`429` with a `Retry-After` header. In-process only — put a shared store
(Redis) behind `SlidingWindowLimiter` if you run more than one instance.

### Background cleanup
A loop started in the app lifespan purges expired rows from `token_denylist`,
`oauth_states`, `email_verification_tokens`, `password_reset_tokens` every
`CLEANUP_INTERVAL_SECONDS`. Run it by hand:
`python -c "import asyncio; from app.services.maintenance import run_cleanup_once; asyncio.run(run_cleanup_once())"`.

## Tests
```bash
uv run pytest        # 32 tests, in-memory SQLite, no external services
```

## User-journey script
With the server running (`uv run uvicorn app.main:app --reload`):
```bash
uv run python scripts/user_journey.py
```
Walks register → me → login → refresh → forgot/reset password → logout, printing
every request/response, then prints a clickable **Google sign-in** link that
lands on `/dev/oauth-landing` so you can see the `?token=` round trip in a browser.

## Google Cloud setup
- **Credentials → OAuth 2.0 Client IDs → (your Web client):** Authorized redirect
  URIs must list every `GOOGLE_REDIRECT_URI` verbatim
  (`http://localhost:8000/api/auth/google/callback`,
  `https://api.zentbookings.com/api/auth/google/callback`).
- **OAuth consent screen / Branding:** app name "Zent", logo, support email,
  app domain links, and authorized domain `zentbookings.com`.
