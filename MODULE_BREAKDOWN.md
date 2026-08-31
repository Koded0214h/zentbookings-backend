# Zent Platform — Backend Module Breakdown

> Derived from [`PRODUCT_REQUIREMENTS.md`](./PRODUCT_REQUIREMENTS.md) v1.0
> Purpose: decompose the backend into top-level modules, each with submodules,
> so work can be split, estimated, and owned independently.
> Modules 1–3 are built. Module 4 (Staff, Roles & Attendance) is scoped, not built.

---

## Overview

| # | Module | Responsibility | Primary PRD sections |
|---|---|---|---|
| 1 | **Identity & Access** | Who the user is, how they authenticate, session lifecycle | 3.5, 3.6, 4.1, 4.4 (User), 5.3, 5.4, 6.2 |
| 2 | **Property Catalogue** | Storing, curating, searching and serving property listings + media | 3.1–3.3, 4.2, 4.4 (Property), 6.1 |
| 3 | **Tour Booking** | Scheduling, confirming and notifying property tours | 3.3 (Tour Modal), 4.3, 4.4 (TourBooking), 6.3 |
| 4 | **Staff, Roles & Attendance** | Role split (user / agent / admin), user administration, agent assignment, staff clock-in/out, login & presence tracking, audit log | 2.2 (Agent persona), 2.3, — (extends 4.1/4.4) |

Cross-cutting concerns (CORS, HTTPS, config, error envelope, rate limiting,
observability) are shared infrastructure consumed by every module — noted
per-module where they bite, not treated as a product module.

---

## Module 1 — Identity & Access

Owns the user record and every path to an authenticated session. Everything else
in the platform trusts a validated `userId` from this module.

### 1.1 Registration & Credentials
- `POST /auth/register` — create user from `firstName`, `lastName`, `email`, `password`
- Password hashing with bcrypt (min cost 10)
- Email uniqueness enforcement + friendly conflict errors
- Server-side mirror of frontend validation (email format, password ≥ 8 chars)
- Returns `{ token, user }` auth response

### 1.2 Login & Session Issuance
- `POST /auth/login` — email + password → `{ token, user }`
- `POST /auth/logout` — clear/invalidate session
- JWT Bearer issuance, 7-day expiry, refresh-on-activity
- Token contract: frontend stores as `zent_auth_token`, sends `Authorization: Bearer <token>`
- 401 semantics so frontend can clear token and redirect to `/signin`

### 1.3 OAuth (Google / Apple)
- `GET /auth/google` and `GET /auth/apple` redirect entrypoints (accept `?redirect_uri`)
- Standard PKCE flow, provider callback handling
- Account linking / creation from OAuth profile
- Post-flow redirect to `https://zentbookings.com/?token={jwt}`
- Google consent screen config: app name "Zent", authorized domain `zentbookings.com`
- **Open item:** OAuth domain setup in Google Cloud Console (PRD §9.1)

### 1.4 User Profile
- `GET /auth/me` — return authenticated user profile
- `User` model: `id`, `email`, `firstName?`, `lastName?`, `fullName?`, `avatarUrl?`, `createdAt?`
- `fullName` derivation, `avatarUrl` handling (nullable)
- Profile is the identity source consumed by Tour Booking (visitor pre-fill)

### 1.5 Account Lifecycle & Transactional Email
- Email verification flow (auto-confirm vs. "check your email" state) — **Open item PRD §9.2**
- Password reset flow (`/forgot-password` frontend route exists)
- SMTP integration (Resend / SendGrid / Postmark)
- Templates: account confirmation, password reset

### 1.6 Access Control Middleware (shared)
- Bearer token verification middleware used by Property (write ops) and Tour modules
- Role concept for admin/agent-only property mutations
- CORS allowlist for `https://zentbookings.com`, HTTPS-only in production

---

## Module 2 — Property Catalogue

Owns property data, its curation workflow, search, and media delivery. Read-heavy
and public; writes are privileged.

### 2.1 Listing & Pagination
- `GET /properties` — paginated listing
- Response envelope: `properties[]`, `total`, `page`, `limit`, `totalPages`
- Offset pagination (`?page=1&limit=9`) — confirm vs. cursor — **Open item PRD §9.4**
- p95 < 200ms target for listing (PRD §6.1) → indexing + caching strategy

### 2.2 Search & Filtering
- Query params: `category` (Rent/Shortlet), `location`, `type`, `priceMin`, `priceMax`
- Maps to frontend URL filter state (`?category=Rent&location=Lekki&type=Monthly&price=…`)
- Location matching (partial/contains), price range, category/type facets
- Filter combinations must compose predictably for active-chip UX

### 2.3 Property Detail
- `GET /properties/:id` — full single-property profile
- Serves gallery, highlights (beds/baths/sqft/price/yearBuilt), full description, amenities

### 2.4 Property Data Model
- `Property`: `id` (number), `title`, `location`, `image`, `gallery[]`, `beds`, `baths`,
  `sqft`, `price`, `period` (`Per Month` | `Per Night`), `yearBuilt`, `amenities[]`,
  `description`, `fullDescription`, `dotColor`, `category` (`Rent` | `Shortlet`)
- Seed data: 72 properties across 8 pages @ 9/page

### 2.5 Curation / Admin CRUD
- `POST /properties`, `PUT /properties/:id`, `DELETE /properties/:id` (admin/agent only)
- Guarded by Module 1 access-control middleware
- Admin panel vs. backend seeding decision — **Open item PRD §9.5**

### 2.6 Media Storage & CDN
- Image + gallery storage: S3 / GCS vs. backend-served — **Open item PRD §9.3**
- CDN URL pattern for `image` and `gallery[]` (e.g. `https://cdn.zentbookings.com/images/prop-1.jpg`)
- Upload/processing pipeline if admin uploads are supported

---

## Module 3 — Tour Booking

Owns the scheduling lifecycle from "Schedule a Tour" click to confirmation and
notification. Depends on Module 1 (auth/user) and references Module 2 (`propertyId`).

### 3.1 Booking Creation
- `POST /tours` — body: `propertyId`, `visitorName`, `visitorEmail`, `visitorPhone`,
  `scheduledDate`, `scheduledTime`, `notes?`
- Response: `id`, `propertyId`, `status`, `scheduledAt` (ISO), `confirmationCode` (e.g. `ZENT-9021`)
- Combine `scheduledDate` + `scheduledTime` → `scheduledAt`; validate not in the past
- Visitor fields pre-filled from authenticated session (Module 1)

### 3.2 Booking Management
- `GET /tours` — list tours for the authenticated user
- `DELETE /tours/:id` — cancel a tour (ownership check)
- Status model: `PENDING` | `CONFIRMED` | `CANCELLED`

### 3.3 Scheduling Rules
- Available time slots per property/day (frontend disables past dates, month/year nav)
- Slot capacity / double-booking prevention
- Confirmation code generation (unique, human-readable)

### 3.4 Tour Data Model
- `TourBooking`: `id` (string), `propertyId` (number), `userId` (string),
  `visitorName`, `visitorEmail`, `visitorPhone`, `scheduledAt`, `notes?`,
  `status`, `confirmationCode`

### 3.5 Notifications
- Tour confirmation email (template in PRD §6.3)
- Optional SMS confirmation — provider TBD — **Open item PRD §9.6**
- Trigger points: on create (confirm), on cancel

---

## Module 4 — Staff, Roles & Attendance

> **Status: scoped, not built.** Today there is a `role` column (`user | agent |
> admin`) and one gate — `require_roles("admin","agent")` — so admin and agent
> are functionally identical, role changes are CLI-only (`scripts/grant_role.py`),
> and there is no attendance or presence tracking. This module makes the split
> real, adds an admin surface for managing people, and tracks staff working time.

Extends Module 1's `User` and auth flows; re-gates privileged endpoints across
Modules 2 and 3; hangs an auto clock-out sweep off the Module 3 maintenance loop.

### 4.1 Role model & permission split
- Roles stay `user` (default: tenant/buyer), `agent` (Zent-certified advisor),
  `admin` (platform operator). Room left for `superadmin` later.
- Replace the single `require_roles("admin","agent")` with two dependencies:
  - `require_staff` → `agent` or `admin`
  - `require_admin` → `admin` only
- Re-gate existing endpoints:
  - **staff:** `POST/PUT /properties`, all `/media/*`, `GET/PUT /properties/{id}/schedule`,
    `POST /tours/{id}/confirm`, tour cancel/reschedule, staff branch of `GET /tours`
  - **admin only:** `DELETE /properties/{id}` (destructive, cascades tours) — *decision*
- `is_active=false` already blocks a token in `get_current_user`; reuse for deactivation.

### 4.2 User & role administration (admin)
- `GET /admin/users` — search/filter by role, status, email; paginated
- `GET /admin/users/{id}` — profile + `role`, `isActive`, login/presence fields, attendance summary
- `PATCH /admin/users/{id}/role` — set role; **last-admin guard** (refuse if it would
  leave zero active admins)
- `PATCH /admin/users/{id}/status` — activate / deactivate
- `POST /admin/agents/invite` *(optional)* — create an `agent` account + send a
  set-password email, so staff onboard without self-signup
- Every mutation writes an audit entry (4.6)

### 4.3 Agent assignment & scoped views
- `property_agents` join table: `property_id`, `agent_id`, `assigned_by`, `assigned_at`
- `POST /admin/properties/{id}/agents` / `DELETE /admin/properties/{id}/agents/{agentId}`
- `GET /agent/properties` — the caller's assigned properties
- `GET /agent/tours` — tours for the caller's assigned properties (status pipeline view)
- **Decision:** hard scoping (agents only see/act on assigned properties) vs. soft
  (assignment is a label; all staff still see everything). Affects the `GET /tours`
  staff branch and schedule/confirm authz.
- Lead tracking (PRD persona 2 "track active leads") kept light: each tour is a lead;
  an optional `leadStatus` (`NEW | CONTACTED | TOURED | NEGOTIATING | CLOSED | LOST`)
  on the tour row, editable by the assigned agent — *build now or defer*

### 4.4 Staff attendance (clock-in / clock-out)
- `StaffAttendance` model: `id`, `userId`, `clockInAt`, `clockOutAt?`,
  `durationMinutes?` (set on close), `source` (`web | mobile | api`), `ip`,
  `userAgent`, `autoClosed` (bool), `note?`, `createdAt`
- Partial unique index: at most one open session (`clockOutAt IS NULL`) per user
- `POST /staff/clock-in` → 201; `409` if already clocked in; captures ip / UA / source
- `POST /staff/clock-out` → 200; `409` if no open session; computes duration
- `GET /staff/me/status` → `{ clockedIn, since, todayMinutes }`
- `GET /staff/attendance/me` → paginated history + current open session + today/week totals
- `GET /admin/attendance` → all staff; filter `userId`, `from`, `to`, `status`; paginated
- `GET /admin/attendance/summary` → hours per user per day / week (reporting)
- `PATCH /admin/attendance/{id}` → admin correction of a bad record (audited)
- **Auto clock-out:** maintenance loop closes sessions open past
  `ATTENDANCE_AUTO_CLOSE_HOURS` (default 16), flags `autoClosed=true`
- Clock-in requires an authenticated staff session; logout does **not** force a
  clock-out (rely on auto-close) — *decision*

### 4.5 Login & presence tracking ("last login")
- Add to `User`: `lastLoginAt`, `lastLoginIp`, `lastLoginMethod`
  (`password | google | apple | refresh`), `lastSeenAt`
- `lastLogin*` written on successful `/auth/login`, OAuth callback, `/auth/refresh`
- `lastSeenAt` updated opportunistically on any authenticated request, throttled to
  once per `LAST_SEEN_THROTTLE_SECONDS` (default 900) to avoid a write per request
- Surfaced in `GET /auth/me` (optional) and the admin user list/detail
- Distinct from 4.4: login is an automatic auth event; clock-in is an explicit
  "on shift" action

### 4.6 Audit log
- `AuditLog` model: `id`, `actorUserId?` (null = system), `action`
  (`role.change`, `user.deactivate`, `property.delete`, `tour.confirm`,
  `attendance.edit`, `agent.assign`, …), `targetType`, `targetId`, `metadata`
  (JSON), `ip`, `createdAt`
- Written by admin/staff mutating endpoints across all modules
- `GET /admin/audit` — paginated; filter by actor, action, target, date range
- Retention: keep indefinitely by default; `AUDIT_RETENTION_DAYS` optional prune
  via the maintenance loop

### Permissions matrix
| Capability | user | agent | admin |
|---|:--:|:--:|:--:|
| Browse properties, book tours | ✓ | ✓ | ✓ |
| Create / update property, upload media | · | ✓ | ✓ |
| Delete property | · | · | ✓ |
| Edit a property's tour schedule | · | ✓¹ | ✓ |
| View all tours; confirm / cancel / reschedule | · | ✓¹ | ✓ |
| Clock in/out, view own attendance | · | ✓ | ✓ |
| List users, change roles, (de)activate | · | · | ✓ |
| Assign agents to properties | · | · | ✓ |
| View all attendance + reports | · | · | ✓ |
| View audit log | · | · | ✓ |

¹ Scoped to assigned properties if 4.3 hard-scoping is chosen; otherwise global.

### Data model changes
- **`users`** — add `last_login_at`, `last_login_ip`, `last_login_method`,
  `last_seen_at` (migration 0005)
- **`property_agents`**, **`staff_attendance`**, **`audit_log`** — new (migration 0006)
- **`agent_profiles`** *(optional, migration 0007)* — `title`, `bio`, `phone`,
  `linkedin_url`, `headshot_url` for the PRD About "Meet the Team" section
  (may stay static frontend content — *decision*)

### Config additions
`ATTENDANCE_AUTO_CLOSE_HOURS=16`, `LAST_SEEN_THROTTLE_SECONDS=900`,
`AUDIT_RETENTION_DAYS=0` (0 = keep forever).

### Ties to existing modules
- **M1:** extends `User`; auth flows write `lastLogin*`; `require_staff` /
  `require_admin` replace `require_roles(...)`
- **M2:** `DELETE /properties` → admin; create/update/media/schedule → staff;
  optional agent scoping via `property_agents`
- **M3:** confirm/cancel/**reschedule** (currently deferred — lands here) → staff;
  agent-scoped tour + lead views
- **Maintenance loop:** add auto clock-out sweep; optional audit prune

### Decisions to settle before building
1. `DELETE /properties` — admin-only, or leave it staff?
2. Agent scoping — hard (assigned-only) or soft (label only)?
3. Agent onboarding — `POST /admin/agents/invite` with set-password email, or keep
   `grant_role.py` only?
4. Last-admin guard — block any role/status change that leaves zero active admins (yes)
5. `lastSeenAt` — throttled column update, separate presence table, or skip
6. Attendance reporting timezone — per-user `tz` field or global `Africa/Lagos`
7. Lead pipeline (`leadStatus` on tours) — build in 4.3 now or defer
8. `agent_profiles` — build now or leave "Meet the Team" as static frontend
9. Mobile clock-in extras (location capture / geofence) — in scope or later

---

## Module dependency map

```
Identity & Access (1)
   ├── provides userId + auth middleware ──► Property Catalogue (2)  [write ops]
   ├── provides userId + visitor profile ──► Tour Booking (3)
   └── provides User + auth flows ────────► Staff, Roles & Attendance (4)
Property Catalogue (2)
   ├── provides propertyId reference ─────► Tour Booking (3)
   └── property mutations re-gated by ────► Staff, Roles & Attendance (4)
Tour Booking (3)
   ├── maintenance loop hosts ────────────► Staff attendance auto clock-out (4.4)
   └── confirm/cancel/reschedule re-gated ► Staff, Roles & Attendance (4)
```

Build order: **1 → 2 → 3 → 4**. Modules 2 and 3 can proceed in parallel once
Module 1's auth middleware and User model are stable. Module 4 comes last: it
re-gates endpoints that Modules 2 and 3 already expose and extends Module 1's
`User`.

---

## Suggested ownership & sequencing

| Phase | Deliverable | Modules |
|---|---|---|
| P0 | Auth (register/login/me/logout) + JWT middleware + User model | 1.1, 1.2, 1.4, 1.6 |
| P1 | Property listing + filtering + detail + seed data | 2.1–2.4 |
| P2 | Tour booking create/list/cancel + confirmation email | 3.1, 3.2, 3.4, 3.5 |
| P3 | OAuth, email verification, password reset | 1.3, 1.5 |
| P3 | Property admin CRUD + media/CDN pipeline | 2.5, 2.6 |
| P3 | Scheduling rules / slot capacity / SMS | 3.3, 3.5 |
| P4a | Role split (`require_staff`/`require_admin`) + login/presence tracking + admin user list / role / status + last-admin guard | 4.1, 4.2, 4.5 |
| P4b | `staff_attendance` + clock in/out + own history + auto clock-out sweep | 4.4 |
| P4c | `property_agents` + agent-scoped views + admin assignment endpoints | 4.3 |
| P4d | `audit_log` + admin audit view; optional `agent_profiles` | 4.6 |
