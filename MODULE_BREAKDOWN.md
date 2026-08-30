# Zent Platform — Backend Module Breakdown

> Derived from [`PRODUCT_REQUIREMENTS.md`](./PRODUCT_REQUIREMENTS.md) v1.0
> Purpose: decompose the backend into 3 top-level modules, each with submodules,
> so work can be split, estimated, and owned independently.

---

## Overview

| # | Module | Responsibility | Primary PRD sections |
|---|---|---|---|
| 1 | **Identity & Access** | Who the user is, how they authenticate, session lifecycle | 3.5, 3.6, 4.1, 4.4 (User), 5.3, 5.4, 6.2 |
| 2 | **Property Catalogue** | Storing, curating, searching and serving property listings + media | 3.1–3.3, 4.2, 4.4 (Property), 6.1 |
| 3 | **Tour Booking** | Scheduling, confirming and notifying property tours | 3.3 (Tour Modal), 4.3, 4.4 (TourBooking), 6.3 |

Cross-cutting concerns (CORS, HTTPS, config, error envelope, rate limiting,
observability) are shared infrastructure consumed by all three modules — noted
per-module where they bite, not treated as a fourth product module.

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

## Module dependency map

```
Identity & Access (1)
   ├── provides userId + auth middleware ──► Property Catalogue (2)  [write ops]
   └── provides userId + visitor profile ──► Tour Booking (3)
Property Catalogue (2)
   └── provides propertyId reference ─────► Tour Booking (3)
```

Build order: **1 → 2 → 3**. Modules 2 and 3 can proceed in parallel once the auth
middleware and User model from Module 1 are stable.

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
