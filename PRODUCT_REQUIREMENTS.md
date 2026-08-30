# Zent Platform — Product Requirements Document (PRD)

> **Version:** 1.0 — Pre-Backend Integration  
> **Prepared by:** Frontend team  
> **Audience:** Backend engineering, product stakeholders  
> **Status:** Frontend complete · Backend integration in progress

---

## 1. Product Overview

### 1.1 Vision
**Zent** is a luxury real estate platform built for the Lagos market. It connects discerning tenants and buyers with premium curated properties — including shortlets, long-term rentals, and sales — delivered through a premium digital experience that reflects the standard of the properties it showcases.

### 1.2 Tagline
*"Crafted for the discerning."*

### 1.3 Core Problem Statement
The Lagos luxury rental and shortlet market is fragmented. Premium properties are listed on general platforms alongside budget options, with no differentiation in quality, user experience, or curation. Prospective tenants waste hours browsing unverified listings and scheduling tours through informal channels.

Zent solves this by acting as a curated marketplace where every property has been vetted, every booking is digital, and every interaction reflects a luxury standard.

---

## 2. User Personas

### 2.1 The Tenant / Buyer
- **Profile:** Lagos-based professional or diaspora returnee, 28–50, HNI segment  
- **Goal:** Find a verified premium apartment or shortlet quickly; book a tour digitally; understand pricing clearly  
- **Pain points:** Can't trust unverified listings; hates wasting time on tours for properties that don't match their standard; wants everything in one platform  

### 2.2 The Property Agent / Advisor
- **Profile:** Zent-certified real estate advisors who manage client relationships  
- **Goal:** Match clients to the right property; schedule and manage tours; track client interest  
- **Pain points:** Fragmented communication; no centralized system to track active leads  

### 2.3 The Property Owner / Developer
- **Profile:** High-net-worth individual or development company listing premium properties  
- **Goal:** List properties on a platform that maintains the prestige of their asset  
- **Pain points:** General platforms devalue their property with poor presentation and unqualified leads  

---

## 3. Features Built (Frontend)

### 3.1 Public Landing Page (`/`)
The home page introduces Zent's brand and drives both property discovery and account creation.

**Sections built:**
| Section | Description |
|---|---|
| **Navbar** | Sticky pill-shaped navigation with smooth scroll, active section detection, mobile hamburger menu, and auth-aware user avatar dropdown |
| **Hero** | Full-bleed background image with category toggle (Rent / Shortlet), location input, type filter, price filter, and CTA search button |
| **Floating Category Section** | Visual category pills (Duplex, Penthouse, Studio, etc.) for quick filtering |
| **Curated Properties Section** | Grid of featured properties with filter controls; paginated to 72 properties across 8 pages (9/page) |
| **Why Choose Us** | Value proposition section with feature highlights |
| **FAQ Section** | Accordion-style FAQ for common questions |
| **Who Can Use Zent** | Section differentiating tenant, buyer, and shortlet seeker personas |
| **Key Stats Highlights** | Animated stat counters (e.g. properties listed, successful placements) |
| **Footer** | Navigation links, contact, brand wordmark |

---

### 3.2 Properties Listing Page (`/properties`)
Full property catalogue with search and filtering.

**Features:**
- URL-based filter state (`?category=Rent&location=Lekki&type=Monthly&price=...`)
- Filter bar: Category (Rent/Shortlet), Location search, Type, Price range
- Property grid (9 per page) with pagination
- Each property card shows: image, title, location, beds, baths, sqft, price/period
- Active filter chips with individual clear capability

**Data fields per property:**
```
id, title, location, image, gallery[], beds, baths, sqft, price, period,
yearBuilt, amenities[], description, fullDescription, dotColor
```

---

### 3.3 Property Detail Page (`/properties/[id]`)
Full property profile with booking capability.

**Sections:**
- Gallery carousel (main image + gallery thumbnails)
- Property highlights: beds, baths, sqft, price, year built
- Full description (rich text)
- Amenities list with icon tags
- "Schedule a Tour" CTA → triggers Tour Modal

**Tour Modal:**
- Calendar date picker (month/year navigation, disabled past dates)
- Time slot selector
- Pre-filled visitor name and email from authenticated user session
- Phone number and notes fields
- Booking confirmation state

---

### 3.4 About Page (`/about`)
Brand identity and team presentation page.

**Sections:**
- Brand story and founder quote (Olawunmi Savi)
- Company stats bar (animated)
- Meet the Team grid (4 team members with photos, roles, bios, LinkedIn)
- Defining Pillars (3 core philosophy cards)
- CTA banner linking to properties and advisor contact

---

### 3.5 Authentication

#### Sign Up (`/signup`)
- Fields: First Name, Last Name, Email, Password, Confirm Password
- Full client-side validation (regex email, min 8-char password, password match)
- Social sign-up buttons: Google, Apple
- Success state → redirects to home after 2s
- Error state with inline field errors and global error banner

#### Sign In (`/signin`)
- Fields: Email, Password (with show/hide toggle)
- Forgot Password link (`/forgot-password`)
- Social sign-in: Google, Apple
- Error handling with friendly user-facing messages

---

### 3.6 Auth-Aware Navigation (Navbar)
- When logged out: Sign In, Sign Up CTA buttons
- When logged in: User avatar with initials/photo, dropdown menu with:
  - Displayed name and email
  - Navigation links
  - Sign Out

---

## 4. Backend API Requirements

### 4.1 Authentication Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Register new patient user |
| `POST` | `/auth/login` | Authenticate user (email + password) |
| `GET` | `/auth/google` | Google OAuth redirect (with `?redirect_uri`) |
| `GET` | `/auth/apple` | Apple OAuth redirect |
| `GET` | `/auth/me` | Return authenticated user profile |
| `POST` | `/auth/logout` | Clear session |

**Auth strategy:** JWT Bearer token, stored in `localStorage` as `zent_auth_token`. Frontend attaches `Authorization: Bearer <token>` on all authenticated requests.

#### Register Request Body
```json
{
  "firstName": "Amara",
  "lastName": "Adeyemi",
  "email": "amara@example.com",
  "password": "SecurePass123"
}
```

#### Login Request Body
```json
{ "email": "amara@example.com", "password": "SecurePass123" }
```

#### Auth Response (register + login)
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "usr_abc123",
    "email": "amara@example.com",
    "firstName": "Amara",
    "lastName": "Adeyemi",
    "fullName": "Amara Adeyemi",
    "avatarUrl": null,
    "createdAt": "2026-08-28T20:00:00Z"
  }
}
```

#### GET /auth/me Response (User profile)
```json
{
  "id": "usr_abc123",
  "email": "amara@example.com",
  "firstName": "Amara",
  "lastName": "Adeyemi",
  "fullName": "Amara Adeyemi",
  "avatarUrl": "https://cdn.example.com/avatar.jpg",
  "createdAt": "2026-08-28T20:00:00Z"
}
```

#### Google/Apple OAuth
- Frontend redirects to: `{API_BASE_URL}/auth/google?redirect_uri=https://zentbookings.com/`
- Backend completes OAuth flow, then redirects to: `https://zentbookings.com/?token={jwt}`
- Frontend reads `?token` from URL, stores in localStorage, calls `/auth/me`

**Google OAuth display name:** The Google consent screen should show **"Zent"** as the application name with `zentbookings.com` as the authorized domain.

---

### 4.2 Properties Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/properties` | Paginated property listing |
| `GET` | `/properties/:id` | Single property detail |
| `POST` | `/properties` | Create property listing (admin/agent) |
| `PUT` | `/properties/:id` | Update property listing |
| `DELETE` | `/properties/:id` | Remove listing |

#### GET /properties — Query Parameters
| Param | Type | Example |
|---|---|---|
| `page` | number | `1` |
| `limit` | number | `9` |
| `category` | string | `Rent` or `Shortlet` |
| `location` | string | `Lekki` |
| `type` | string | `Monthly` |
| `priceMin` | number | `50000` |
| `priceMax` | number | `500000` |

#### GET /properties Response
```json
{
  "properties": [
    {
      "id": 1,
      "title": "The Obsidian Loft",
      "location": "Victoria Island, Lagos",
      "image": "https://cdn.zentbookings.com/images/prop-1.jpg",
      "gallery": ["..."],
      "beds": 3,
      "baths": 3,
      "sqft": 2800,
      "price": 85000,
      "period": "Per Month",
      "yearBuilt": 2023,
      "amenities": ["Smart Home System", "Private Pool", "24/7 Security"],
      "description": "Where Precision Meets Panorama",
      "fullDescription": "Full property writeup...",
      "dotColor": "#FFE501",
      "category": "Rent"
    }
  ],
  "total": 72,
  "page": 1,
  "limit": 9,
  "totalPages": 8
}
```

---

### 4.3 Tour Booking Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/tours` | Create tour booking |
| `GET` | `/tours` | List tours (authenticated user) |
| `DELETE` | `/tours/:id` | Cancel tour |

#### POST /tours Request Body
```json
{
  "propertyId": 1,
  "visitorName": "Amara Adeyemi",
  "visitorEmail": "amara@example.com",
  "visitorPhone": "+2348012345678",
  "scheduledDate": "2026-09-15",
  "scheduledTime": "14:00",
  "notes": "Interested in long-term lease"
}
```

#### POST /tours Response
```json
{
  "id": "tour_xyz789",
  "propertyId": 1,
  "status": "CONFIRMED",
  "scheduledAt": "2026-09-15T14:00:00Z",
  "confirmationCode": "ZENT-9021"
}
```

---

### 4.4 User Data Models

#### User
```typescript
interface User {
  id: string;           // UUID or prefixed string
  email: string;
  firstName?: string;
  lastName?: string;
  fullName?: string;
  avatarUrl?: string;
  createdAt?: string;   // ISO 8601
}
```

#### Property
```typescript
interface Property {
  id: number;
  title: string;
  location: string;
  image: string;
  gallery: string[];
  beds: number;
  baths: number;
  sqft: number;
  price: number;
  period: "Per Month" | "Per Night";
  yearBuilt: number;
  amenities: string[];
  description: string;
  fullDescription: string;
  dotColor: string;
  category: "Rent" | "Shortlet";
}
```

#### TourBooking
```typescript
interface TourBooking {
  id: string;
  propertyId: number;
  userId: string;
  visitorName: string;
  visitorEmail: string;
  visitorPhone: string;
  scheduledAt: string;
  notes?: string;
  status: "PENDING" | "CONFIRMED" | "CANCELLED";
  confirmationCode: string;
}
```

---

## 5. Frontend ↔ Backend Integration Points

### 5.1 Environment Configuration
```env
VITE_API_BASE_URL=https://api.zentbookings.com/api
```

### 5.2 API Service Layer
File: [`src/services/api.ts`](file:///Users/fiopefoluwaorekoya/Desktop/zent/src/services/api.ts)

All API calls go through the `authApi` object. When the backend is live, simply update `VITE_API_BASE_URL` — no frontend code changes needed.

### 5.3 Auth Context
File: [`src/context/AuthContext.tsx`](file:///Users/fiopefoluwaorekoya/Desktop/zent/src/context/AuthContext.tsx)

Exposes: `{ user, loading, signIn, signUp, signInWithOAuth, signOut }`

### 5.4 Token Management
- JWT stored in `localStorage` as `zent_auth_token`
- User object cached in `localStorage` as `zent_user`
- Frontend checks `/auth/me` on load to refresh user state
- On 401 response, frontend clears token and redirects to `/signin`

---

## 6. Non-Functional Requirements

### 6.1 Performance
- API response time: < 200ms (p95) for property listing
- Property images served via CDN

### 6.2 Security
- Passwords hashed with bcrypt (min cost 10)
- JWT tokens expire after 7 days; refresh on activity
- Google/Apple OAuth via standard PKCE flow
- HTTPS only in production

### 6.3 Email
- Confirmation emails sent via SMTP (Resend, SendGrid, or Postmark recommended)
- Email templates: account confirmation, tour confirmation, password reset

### 6.4 CORS
```
Access-Control-Allow-Origin: https://zentbookings.com
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type
```

---

## 7. Routing Map

| Route | Component | Auth Required |
|---|---|---|
| `/` | HomePage | No |
| `/properties` | PropertiesPage | No |
| `/properties/:id` | PropertyDetailPage | No |
| `/about` | AboutPage | No |
| `/signin` | SignInPage | No (redirect if authed) |
| `/signup` | SignUpPage | No (redirect if authed) |
| `/forgot-password` | ForgotPasswordPage | No |

---

## 8. Success Metrics

| Metric | Target |
|---|---|
| Time to first property listing from sign-up | < 2 minutes |
| Tour booking completion rate | > 40% of property detail page visitors |
| Auth success rate (sign up) | > 95% |
| Google OAuth adoption rate | > 30% of new sign-ups |
| Mobile bounce rate | < 35% |

---

## 9. Open Items for Backend Team

> [!IMPORTANT]
> These items require backend decisions before frontend can fully integrate.

1. **OAuth domain setup** — Google consent screen must display "Zent" and `zentbookings.com`. Configure in Google Cloud Console under APIs & Credentials → OAuth consent screen.
2. **Email confirmation flow** — Will sign-up auto-confirm or require email verification? If verification required, frontend needs to show a "check your email" state after sign-up.
3. **Property image storage** — Are images stored in S3/GCS or served from backend? CDN URL pattern needed for `image` and `gallery` fields.
4. **Pagination strategy** — Confirm offset-based (`?page=1&limit=9`) vs cursor-based pagination for properties endpoint.
5. **Property create/admin flow** — Is there an admin panel for adding properties, or will the backend team handle data seeding initially?
6. **Tour notifications** — Should tour confirmations trigger email/SMS notifications? If yes, which provider?

---

## 10. Appendix: Pages & Components Built

### Pages
- `src/app/page.tsx` — Home
- `src/app/about/page.tsx` — About
- `src/app/properties/page.tsx` — Property listing
- `src/app/properties/[id]/page.tsx` — Property detail + tour modal
- `src/app/signin/page.tsx` — Sign in
- `src/app/signup/page.tsx` — Sign up

### Key Components
- `Navbar.tsx` — Auth-aware navigation with scroll detection and mobile menu
- `HeroSection.tsx` — Search bar with category/location/type/price filters
- `FloatingCategorySection.tsx` — Property type pill filters
- `CuratedPropertiesSection.tsx` — Paginated property grid with filters
- `WhyChooseUs.tsx` — Value proposition grid
- `FAQSection.tsx` — Accordion FAQ
- `WhoCanUseZent.tsx` — Persona differentiation section
- `KeyStatsHighlights.tsx` — Animated stat counters
- `Footer.tsx` — Footer

### Service Layer
- `src/services/api.ts` — `authApi` with login, register, OAuth, profile, logout
- `src/context/AuthContext.tsx` — Global auth state provider
- `src/types/auth.ts` — TypeScript interfaces for User, AuthResponse, etc.
