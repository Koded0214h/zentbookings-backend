# Zent Backend

FastAPI service. See [`MODULE_BREAKDOWN.md`](./MODULE_BREAKDOWN.md) for full scope.

- **Module 1 — Identity & Access:** registration, login, sessions, OAuth
  (Google live; Apple coded, deferred), profile, email verification, password reset.
- **Module 2 — Property Catalogue:** listing + pagination, search/filter,
  detail, role-gated admin CRUD.
- **Module 3 — Tour Booking:** guest + authed bookings, per-property
  scheduling (slots/capacity/blackouts/timezone), availability lookup,
  staff management, email notifications.
- **Module 4 — Staff, Roles & Attendance:** admin/agent role split, user &
  role administration, agent invite emails, property↔agent assignment,
  lead pipeline on tours, staff clock-in/out + attendance reports,
  login/presence tracking, audit log, public "agents" directory.

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

## Properties (Module 2)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/properties` | – | Paginated listing + filters |
| GET | `/properties/{id}` | – | Single property (404 envelope if missing) |
| POST | `/properties` | admin/agent | Create |
| PUT | `/properties/{id}` | admin/agent | Partial update (only provided keys) |
| DELETE | `/properties/{id}` | admin/agent | Remove (204) |

`GET /properties` query params: `page` (1), `limit` (1–100, default 9),
`category` (Rent/Shortlet, case-insensitive), `location` (case-insensitive
substring), `type` (mapped onto `period`: Monthly→"Per Month",
Nightly→"Per Night"), `priceMin`, `priceMax`, `q` (free-text over
title/location/description), `sort` (`id` | `-id` | `price` | `-price` |
`newest` | `oldest`; default `id`). Response envelope:
`{ properties[], total, page, limit, totalPages }`.

Both GET routes are rate-limited (`LIST_RATE_LIMIT`, default 300/60 per IP) and
send `ETag` + `Cache-Control: public, max-age=<PROPERTIES_CACHE_MAX_AGE>`; a
matching `If-None-Match` gets `304`.

Grant a user staff access: `uv run python scripts/grant_role.py <email> admin`.
Seed 72 demo properties: `uv run python scripts/seed_properties.py [--force]`.

### Media uploads (Cloudinary)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/media/upload` | admin/agent | `multipart/form-data` `files[]` (+ `resource_type` = `image`\|`video`) → `{ assets: [{ url, publicId, ... }] }` |
| POST | `/media/sign` | admin/agent | Params for a signed browser→Cloudinary direct upload |
| POST | `/media/delete` | admin/agent | `{ publicId, resourceType }` → destroy one asset |

`image` / `gallery[]` on a property stay plain URL strings (PRD contract).
Pass the optional `imagePublicId` / `galleryPublicIds` from an upload response
when creating/updating a property — they're stored (not returned). Assets are
destroyed on `DELETE /properties/{id}` **and** on `PUT` for any public id the
update dereferences. Needs `CLOUDINARY_*` env vars; endpoints return
`503 media_not_configured` without them.

**Orphan sweep:** the maintenance loop (`run_cleanup_once`) also lists the
Cloudinary folder and destroys any asset no property references (by stored
public id *or* by URL) that is older than `MEDIA_SWEEP_GRACE_SECONDS`
(default 24h). Toggle with `MEDIA_SWEEP_ENABLED`.

## Tours (Module 3)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/properties/{id}/availability` | – | Slots for `?on=YYYY-MM-DD` or `?from=&to=` (default = advance window) |
| POST | `/tours` | optional | Book a tour. Auth optional; if signed in, links the user and fills missing visitor fields from the profile. Rate-limited. |
| GET | `/tours` | Bearer | Own tours; **staff** see all + `?status=`/`?propertyId=` filters. Paginated. |
| GET | `/tours/{id}` | Bearer | Owner or staff |
| DELETE | `/tours/{id}` | Bearer | Owner/staff cancel (soft → `CANCELLED`) |
| POST | `/tours/lookup` | – | Guest self-service: `{ confirmationCode, email }` → tour |
| POST | `/tours/cancel` | – | Guest cancel by `{ confirmationCode, email }` |
| POST | `/tours/{id}/confirm` | admin/agent | `PENDING` → `CONFIRMED` |
| GET/PUT | `/properties/{id}/schedule` | admin/agent | Per-property scheduling config |

`POST /tours` body: `propertyId`, `scheduledDate` (YYYY-MM-DD), `scheduledTime`
(HH:MM), `visitorName?`/`visitorEmail?`/`visitorPhone?` (required for guests;
auto-filled from the account otherwise), `notes?`. Response:
`{ id, propertyId, status, scheduledAt, confirmationCode }` (`ZENT-XXXXXX`).

**Scheduling** (`property_schedules`, lazily created with defaults — Mon–Fri
10:00–17:00, Sat 11:00–15:00, 60-min slots, capacity 1, `auto_confirm` true,
`Africa/Lagos`, 12h min notice, 30-day window): `scheduledDate`+`scheduledTime`
are interpreted in the property's timezone and stored as UTC. A booking is
rejected (`409 slot_unavailable`) if the day is closed/blacked-out/out of
window, the time isn't a slot, it's inside the notice window, or the slot is at
capacity. `auto_confirm=false` → tours land `PENDING` and an agent confirms.

**Emails** (to the visitor address, via the Module 1 sender): tour requested
(pending), confirmed, cancelled. SMS is not wired (PRD open item §9.6).

## Staff, Roles & Attendance (Module 4)

Roles: `user` (default) · `agent` · `admin`. `require_staff` = agent|admin,
`require_admin` = admin only. Bootstrap the first admin with
`uv run python scripts/grant_role.py <email> admin`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/users` | admin | list/filter (`role`, `isActive`, `q`), paginated |
| GET/PATCH | `/admin/users/{id}` · `/role` · `/status` | admin | view / change role / (de)activate — **last-admin guarded** |
| POST | `/admin/agents/invite` | admin | create agent/admin + email a set-password link (`/auth/reset-password` token) |
| GET/POST/DELETE | `/admin/properties/{id}/agents[...]` | admin | list / assign / unassign agents (soft) |
| GET | `/admin/attendance` · `/attendance/summary` | admin | all staff sessions + per-user hours |
| PATCH | `/admin/attendance/{id}` | admin | correct a record (recomputes duration) |
| GET | `/admin/audit` | admin | audit log (`actorId`, `action`, `targetType` filters) |
| POST | `/staff/clock-in` · `/staff/clock-out` | staff | one open session per user (`409` otherwise) |
| GET | `/staff/me/status` · `/staff/attendance/me` | staff | am-I-in + today total; own history |
| GET/PUT | `/staff/me/profile` | staff | own public "Meet the Team" profile |
| GET | `/agent/properties` · `/agent/tours` | staff | scoped to the caller's assigned properties (`leadStatus` filter) |
| GET | `/agents` · `/agents/{id}` | – | public directory of **published** agent profiles |
| PATCH | `/tours/{id}` | staff | reschedule (both `scheduledDate`+`scheduledTime`) and/or set `leadStatus`/`notes` |

**Lead pipeline:** every tour carries `leadStatus`
(`NEW → CONTACTED → TOURED → NEGOTIATING → CLOSED / LOST`), default `NEW`.

**Login & presence:** `/auth/login`, OAuth callbacks and `/auth/refresh` stamp
`lastLoginAt/Ip/Method`; any authed request refreshes `lastSeenAt` at most once
per `LAST_SEEN_THROTTLE_SECONDS` (900). Visible in the admin user views only.

**Auto clock-out:** the maintenance loop force-closes sessions open longer than
`ATTENDANCE_AUTO_CLOSE_HOURS` (16, `autoClosed=true`). `AUDIT_RETENTION_DAYS`
(0 = keep) optionally prunes the audit log.

## Observability

A pure-ASGI middleware times every request, records in-memory metrics, and
stamps an `X-Request-ID` header (also exposed via CORS). All endpoints are
**public by default** — set `OBSERVABILITY_TOKEN` to require `?token=` or an
`X-Observability-Token` header. `OBSERVABILITY_ENABLED=false` disables the
middleware and routes entirely.

| Path | |
|---|---|
| `GET /observability` | self-contained HTML dashboard (inline CSS/JS, auto-refresh 3s) — uptime, req/s, error rate, p50/p90/p99 latency, status-class bar, top/slowest routes, recent errors + requests |
| `GET /observability/metrics` | JSON snapshot the dashboard polls |
| `GET /observability/logs` | recent request + error ring buffers |
| `GET /observability/prometheus` | Prometheus text exposition |

Metrics are in-memory (single instance, reset on restart): latency percentiles
over the last `METRICS_SAMPLE_SIZE` (2000) requests, ring buffers of the last
`METRICS_RECENT_SIZE` (100). Route labels are low-cardinality templates
(`/api/properties/{property_id}`); its own paths, `/health`, and docs are not
counted. Logging is configured by `LOG_LEVEL` and `LOG_FORMAT` (`text` | `json`);
sensitive query params (`token`, `code`, `password`, …) are redacted before
anything is logged or stored.

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
`oauth_states`, `email_verification_tokens`, `password_reset_tokens` and sweeps
orphaned Cloudinary assets every `CLEANUP_INTERVAL_SECONDS`. Run it by hand:
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
