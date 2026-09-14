#!/usr/bin/env python
"""Send one real email through Resend's HTTPS API.

    uv run python scripts/test_resend.py [recipient]

Defaults recipient to coder0214h@gmail.com. Forces the Resend sender
regardless of PROD so you can verify RESEND_API_KEY / RESEND_FROM actually
work, the same way scripts/test_email.py does for SMTP.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from app.core.config import settings
from app.services.email.resend import ResendEmailSender


async def main() -> int:
    to = sys.argv[1] if len(sys.argv) > 1 else "coder0214h@gmail.com"

    print("Resend config in use:")
    print(f"  from      {settings.RESEND_FROM or settings.SMTP_FROM}")
    print(f"  key set   {bool(settings.RESEND_API_KEY)}")
    print(f"  -> {to}\n")

    if not settings.RESEND_API_KEY:
        print("RESEND_API_KEY not set in .env")
        return 1

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        await ResendEmailSender().send(
            to=to,
            subject=f"Zent Resend test — {stamp}",
            html=(
                "<h2>Zent Resend test</h2><p>If you're reading this, the backend's "
                f"Resend configuration works.</p><p>Sent {stamp}.</p>"
            ),
            text=f"Zent Resend test. Config works. Sent {stamp}.",
        )
    except Exception as exc:  # noqa: BLE001 - surface the real reason
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("Sent OK. Check the inbox (and spam).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
