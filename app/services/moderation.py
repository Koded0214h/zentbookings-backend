"""Flag-and-allow content moderation for in-app messages.

Scope (per the mock UI's "no sharing contact info" rule): catch obvious
phone numbers and bank account numbers so staff/guests are nudged to keep
contact off-platform, without blocking the message outright.
"""

from __future__ import annotations

import re

# A run of 7+ digits, optionally separated by spaces/dashes/dots/parens —
# catches both phone numbers and 10-11 digit Nigerian bank account numbers.
_DIGIT_RUN = re.compile(r"(?:\d[\s\-.()]?){7,}\d")
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def check(body: str) -> str | None:
    """Return a flag reason if `body` looks like it shares contact info, else None."""
    if _DIGIT_RUN.search(body):
        return "possible phone/account number"
    if _EMAIL.search(body):
        return "possible email address"
    return None
