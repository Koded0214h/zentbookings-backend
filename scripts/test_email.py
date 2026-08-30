#!/usr/bin/env python
"""Send one real email through the configured SMTP settings.

    uv run python scripts/test_email.py [recipient]

Defaults recipient to coder0214h@gmail.com. Forces the SMTP sender regardless
of PROD so you can verify the mailbox credentials in .env actually work.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from app.core.config import settings
from app.services.email.smtp import SMTPEmailSender


async def main() -> int:
    to = sys.argv[1] if len(sys.argv) > 1 else "coder0214h@gmail.com"

    print("SMTP config in use:")
    print(f"  host      {settings.SMTP_HOST}:{settings.SMTP_PORT}")
    print(f"  security  {settings.SMTP_SECURITY}")
    print(f"  user      {settings.SMTP_USER}")
    print(f"  from      {settings.SMTP_FROM}")
    print(f"  -> {to}\n")

    if not settings.SMTP_HOST or not settings.SMTP_USER:
        print("SMTP_HOST / SMTP_USER not set in .env")
        return 1

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        await SMTPEmailSender().send(
            to=to,
            subject=f"Zent SMTP test — {stamp}",
            html=(
                "<h2>Zent SMTP test</h2><p>If you're reading this, the backend's "
                f"email configuration works.</p><p>Sent {stamp}.</p>"
            ),
            text=f"Zent SMTP test. Config works. Sent {stamp}.",
        )
    except Exception as exc:  # noqa: BLE001 - surface the real reason
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("Sent OK. Check the inbox (and spam).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
