#!/usr/bin/env python
"""Walk a real user through Module 1 against a running server.

    uv run uvicorn app.main:app --reload      # in one terminal
    uv run python scripts/user_journey.py     # in another

Every step prints the request and the response. The password-reset and
email-verify steps read their one-time token straight out of the dev
console-email log line, so run the server with PROD unset.

Env:
    BASE_URL   default http://localhost:8000
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"

C_OK = "\033[92m"
C_DIM = "\033[2m"
C_HEAD = "\033[96m"
C_ERR = "\033[91m"
C_END = "\033[0m"


def head(title: str) -> None:
    print(f"\n{C_HEAD}=== {title} ==={C_END}")


def show(method: str, path: str, resp: httpx.Response) -> dict:
    ok = resp.status_code < 400
    colour = C_OK if ok else C_ERR
    print(f"{C_DIM}{method} {path}{C_END} -> {colour}{resp.status_code}{C_END}")
    try:
        body = resp.json()
        print(f"{C_DIM}{body}{C_END}")
        return body
    except ValueError:
        print(f"{C_DIM}{resp.text[:200]}{C_END}")
        return {}


async def main() -> int:
    email = f"journey+{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123"
    new_password = "EvenBetterPass456"

    async with httpx.AsyncClient(timeout=15) as c:
        # 1. health
        head("Health check")
        r = await c.get(f"{BASE_URL}/health")
        show("GET", "/health", r)
        if r.status_code != 200:
            print(f"{C_ERR}Server not reachable at {BASE_URL}. Start it first.{C_END}")
            return 1

        # 2. register
        head("Register")
        r = await c.post(
            f"{API}/auth/register",
            json={
                "firstName": "Journey",
                "lastName": "Tester",
                "email": email,
                "password": password,
            },
        )
        body = show("POST", "/api/auth/register", r)
        token = body.get("token")
        if not token:
            return 1
        auth = {"Authorization": f"Bearer {token}"}

        # 3. me
        head("GET /auth/me with the register token")
        show("GET", "/api/auth/me", await c.get(f"{API}/auth/me", headers=auth))

        # 4. login
        head("Login with the same credentials")
        r = await c.post(f"{API}/auth/login", json={"email": email, "password": password})
        body = show("POST", "/api/auth/login", r)
        token = body.get("token", token)
        auth = {"Authorization": f"Bearer {token}"}

        # 5. refresh
        head("Refresh (old token gets revoked)")
        r = await c.post(f"{API}/auth/refresh", headers=auth)
        body = show("POST", "/api/auth/refresh", r)
        new_token = body.get("token")
        print(f"{C_DIM}old token still valid? "
              f"{(await c.get(f'{API}/auth/me', headers=auth)).status_code}{C_END}")
        auth = {"Authorization": f"Bearer {new_token}"}
        print(f"{C_DIM}new token valid? "
              f"{(await c.get(f'{API}/auth/me', headers=auth)).status_code}{C_END}")

        # 6. forgot password  (grab token from server console log)
        head("Forgot password")
        show(
            "POST",
            "/api/auth/forgot-password",
            await c.post(f"{API}/auth/forgot-password", json={"email": email}),
        )
        print(f"{C_DIM}--> check the server console for the reset link "
              f"(console email sender). Paste the token value here.{C_END}")
        raw = input("reset token (blank to skip reset steps): ").strip()

        if raw:
            reset_token = _clean_token(raw)
            head("Reset password")
            show(
                "POST",
                "/api/auth/reset-password",
                await c.post(
                    f"{API}/auth/reset-password",
                    json={"token": reset_token, "password": new_password},
                ),
            )

            head("Login with the NEW password")
            r = await c.post(
                f"{API}/auth/login", json={"email": email, "password": new_password}
            )
            body = show("POST", "/api/auth/login", r)
            token = body.get("token", new_token)
            auth = {"Authorization": f"Bearer {token}"}

        # 7. logout
        head("Logout")
        show("POST", "/api/auth/logout", await c.post(f"{API}/auth/logout", headers=auth))

        head("GET /auth/me after logout (should be 401)")
        show("GET", "/api/auth/me", await c.get(f"{API}/auth/me", headers=auth))

    # 8. clickable OAuth links
    head("Google OAuth — click these in a browser")
    landing = f"{BASE_URL}/dev/oauth-landing"
    start = f"{API}/auth/google?redirect_uri={landing}"
    print(f"  Start sign-in : {C_OK}{start}{C_END}")
    print(f"  Dev landing   : {C_OK}{landing}{C_END}")
    print(
        f"{C_DIM}  The browser goes to Google, back to {API}/auth/google/callback,\n"
        f"  then to the landing page with ?token=... which it shows and feeds to\n"
        f"  /api/auth/me. Requires GOOGLE_CLIENT_ID/SECRET set and the callback\n"
        f"  URL registered in GCP.{C_END}"
    )
    return 0


def _clean_token(raw: str) -> str:
    m = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", raw)
    return m.group(1) if m else raw


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
