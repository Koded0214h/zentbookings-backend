#!/usr/bin/env python
"""End-to-end walk through all three modules against a running server.

    uv run uvicorn app.main:app --reload       # terminal 1
    uv run python scripts/user_journey.py      # terminal 2

Non-interactive. Prints every request/response, creates real rows (property,
tour, Cloudinary asset), then tears them down. Run with the server on PROD unset
so email goes to the console sender.

Flags:
    --keep     don't delete what the run created
Env:
    BASE_URL   default http://localhost:8000
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"
KEEP = "--keep" in sys.argv[1:]

# 1x1 PNG, uploaded for real to Cloudinary during the Module 2 leg
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

C_OK, C_DIM, C_HEAD, C_ERR, C_END = "\033[92m", "\033[2m", "\033[96m", "\033[91m", "\033[0m"


def head(title: str) -> None:
    print(f"\n{C_HEAD}=== {title} ==={C_END}")


def show(method: str, path: str, resp: httpx.Response) -> dict:
    colour = C_OK if resp.status_code < 400 else C_ERR
    print(f"{C_DIM}{method} {path}{C_END} -> {colour}{resp.status_code}{C_END}")
    try:
        body = resp.json()
        print(f"{C_DIM}{body}{C_END}")
        return body
    except ValueError:
        if resp.text:
            print(f"{C_DIM}{resp.text[:200]}{C_END}")
        return {}


def next_weekday(days_ahead: int = 3) -> str:
    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() >= 5:  # skip Sat/Sun (default schedule)
        d += timedelta(days=1)
    return d.isoformat()


async def main() -> int:
    email = f"journey+{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123"
    created_property_id: int | None = None

    async with httpx.AsyncClient(timeout=30) as c:
        head("Health check")
        if (await c.get(f"{BASE_URL}/health")).status_code != 200:
            print(f"{C_ERR}Server not reachable at {BASE_URL}. Start it first.{C_END}")
            return 1

        # ---------------- Module 1: Identity & Access ----------------
        head("M1 · register")
        body = show(
            "POST", "/api/auth/register",
            await c.post(
                f"{API}/auth/register",
                json={"firstName": "Journey", "lastName": "Tester",
                      "email": email, "password": password},
            ),
        )
        token = body.get("token")
        if not token:
            return 1
        auth = {"Authorization": f"Bearer {token}"}

        head("M1 · me")
        show("GET", "/api/auth/me", await c.get(f"{API}/auth/me", headers=auth))

        head("M1 · login")
        token = show(
            "POST", "/api/auth/login",
            await c.post(f"{API}/auth/login", json={"email": email, "password": password}),
        ).get("token", token)
        auth = {"Authorization": f"Bearer {token}"}

        head("M1 · refresh (old token is revoked)")
        token = show("POST", "/api/auth/refresh",
                     await c.post(f"{API}/auth/refresh", headers=auth)).get("token", token)
        auth = {"Authorization": f"Bearer {token}"}

        head("M1 · forgot-password (always 202; token is in the server console)")
        show("POST", "/api/auth/forgot-password",
             await c.post(f"{API}/auth/forgot-password", json={"email": email}))

        # ---------------- promote to admin (local CLI) ----------------
        head("promote this user to admin via scripts/grant_role.py")
        out = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "grant_role.py"), email, "admin"],
            capture_output=True, text=True, cwd=REPO,
        )
        print(f"{C_DIM}{out.stdout.strip() or out.stderr.strip()}{C_END}")

        # ---------------- Module 2: Property Catalogue ----------------
        head("M2 · list properties")
        listing = show("GET", "/api/properties?limit=3&sort=-price",
                       await c.get(f"{API}/properties", params={"limit": 3, "sort": "-price"}))
        if listing.get("properties"):
            pid = listing["properties"][0]["id"]
            head(f"M2 · detail /properties/{pid}")
            show("GET", f"/api/properties/{pid}", await c.get(f"{API}/properties/{pid}"))

        head("M2 · media upload (real Cloudinary)")
        up = show(
            "POST", "/api/media/upload",
            await c.post(f"{API}/media/upload", headers=auth,
                         files={"files": ("journey.png", PNG_1PX, "image/png")}),
        )
        asset = (up.get("assets") or [{}])[0]

        head("M2 · create property (staff) using the uploaded image")
        created = show(
            "POST", "/api/properties",
            await c.post(
                f"{API}/properties", headers=auth,
                json={
                    "title": "Journey Test Residence", "location": "Ikoyi, Lagos",
                    "image": asset.get("url", "https://example.com/x.jpg"),
                    "imagePublicId": asset.get("publicId"),
                    "gallery": [], "galleryPublicIds": [],
                    "beds": 3, "baths": 3, "sqft": 2200, "price": 1650000,
                    "period": "Per Month", "yearBuilt": 2024,
                    "amenities": ["Gym", "24/7 Security"], "description": "Test",
                    "fullDescription": "Created by user_journey.py", "dotColor": "#FFE501",
                    "category": "Rent",
                },
            ),
        )
        created_property_id = created.get("id")

        head("M2 · update property (partial)")
        show("PUT", f"/api/properties/{created_property_id}",
             await c.put(f"{API}/properties/{created_property_id}",
                         headers=auth, json={"price": 1725000}))

        # ---------------- Module 3: Tour Booking ----------------
        head(f"M3 · schedule for /properties/{created_property_id}")
        show("GET", f"/api/properties/{created_property_id}/schedule",
             await c.get(f"{API}/properties/{created_property_id}/schedule", headers=auth))

        day = next_weekday()
        head(f"M3 · availability on {day}")
        avail = show(
            "GET", f"/api/properties/{created_property_id}/availability?on={day}",
            await c.get(f"{API}/properties/{created_property_id}/availability",
                        params={"on": day}),
        )
        slot_time = (avail.get("slots") or [{"time": "10:00"}])[0]["time"]

        head(f"M3 · guest books {day} {slot_time} (no auth)")
        booking = show(
            "POST", "/api/tours",
            await c.post(
                f"{API}/tours",
                json={
                    "propertyId": created_property_id, "visitorName": "Walk-in Guest",
                    "visitorEmail": "guest@example.com", "visitorPhone": "+2348010000000",
                    "scheduledDate": day, "scheduledTime": slot_time,
                    "notes": "from user_journey.py",
                },
            ),
        )
        code = booking.get("confirmationCode", "")
        tour_id = booking.get("id")

        head("M3 · same slot again -> 409")
        show("POST", "/api/tours",
             await c.post(f"{API}/tours", json={
                 "propertyId": created_property_id, "visitorName": "B",
                 "visitorEmail": "b@example.com", "visitorPhone": "+2348019999999",
                 "scheduledDate": day, "scheduledTime": slot_time}))

        head("M3 · staff lists tours (sees all)")
        show("GET", "/api/tours",
             await c.get(f"{API}/tours", headers=auth,
                         params={"propertyId": created_property_id}))

        head("M3 · guest lookup by code + email")
        show("POST", "/api/tours/lookup",
             await c.post(f"{API}/tours/lookup",
                          json={"confirmationCode": code, "email": "guest@example.com"}))

        head(f"M3 · staff cancels tour {tour_id}")
        show("DELETE", f"/api/tours/{tour_id}",
             await c.request("DELETE", f"{API}/tours/{tour_id}", headers=auth))

        # ---------------- teardown ----------------
        if not KEEP and created_property_id:
            head("teardown · delete property (cascades tours + schedule, frees Cloudinary asset)")
            show("DELETE", f"/api/properties/{created_property_id}",
                 await c.request("DELETE", f"{API}/properties/{created_property_id}", headers=auth))

        head("M1 · logout, then me -> 401")
        show("POST", "/api/auth/logout", await c.post(f"{API}/auth/logout", headers=auth))
        show("GET", "/api/auth/me", await c.get(f"{API}/auth/me", headers=auth))

    if not KEEP:
        await _delete_user(email)

    head("Google OAuth — click in a browser")
    landing = f"{BASE_URL}/dev/oauth-landing"
    print(f"  Start : {C_OK}{API}/auth/google?redirect_uri={landing}{C_END}")
    print(f"  Lands : {C_OK}{landing}{C_END}")
    print(f"{C_DIM}  Needs GOOGLE_CLIENT_ID/SECRET and the callback URL registered in GCP.{C_END}")
    return 0


async def _delete_user(email: str) -> None:
    """Remove the journey user directly (no API endpoint for account deletion)."""
    try:
        from sqlalchemy import text

        from app.core.database import engine

        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
        await engine.dispose()
        print(f"{C_DIM}teardown · deleted user {email}{C_END}")
    except Exception as exc:  # noqa: BLE001
        print(f"{C_ERR}could not delete user {email}: {exc}{C_END}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
