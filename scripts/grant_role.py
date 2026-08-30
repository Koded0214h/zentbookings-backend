#!/usr/bin/env python
"""Set a user's role (user | agent | admin).

    uv run python scripts/grant_role.py user@example.com admin
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User

ROLES = {"user", "agent", "admin"}


async def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in ROLES:
        print(f"usage: grant_role.py <email> <{'|'.join(sorted(ROLES))}>")
        return 2
    email, role = sys.argv[1].strip().lower(), sys.argv[2]
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(f"no user with email {email}")
            return 1
        user.role = role
        await db.commit()
        print(f"{email} is now '{role}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
