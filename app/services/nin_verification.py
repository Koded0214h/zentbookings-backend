"""NIN (Nigerian National Identity Number) verification via Dojah.

Used once, at agent sign-up: the applicant submits their NIN alongside the
usual registration fields, we look it up with Dojah, and the account is
only created if the record is found *and* the registered name matches what
they submitted. Regular user sign-up never touches this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.exceptions import AppError

NIN_PATTERN = re.compile(r"^\d{11}$")


class NinNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(
            503, "nin_not_configured", "Agent identity verification is not configured."
        )


class NinVerificationFailed(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(422, "nin_verification_failed", message)


class NinProviderError(AppError):
    def __init__(self, message: str = "Identity verification provider error.") -> None:
        super().__init__(502, "nin_provider_error", message)


@dataclass(slots=True)
class NinResult:
    registered_name: str
    reference: str


def _normalize(name: str) -> set[str]:
    return {tok for tok in re.sub(r"[^a-z\s]", "", name.lower()).split() if tok}


def _names_match(registered: str, submitted_first: str, submitted_last: str) -> bool:
    tokens = _normalize(registered)
    return submitted_first.strip().lower() in tokens and submitted_last.strip().lower() in tokens


def _headers() -> dict[str, str]:
    return {"AppId": settings.DOJAH_APP_ID or "", "Authorization": settings.DOJAH_SECRET_KEY or ""}


async def verify_nin(nin: str, *, first_name: str, last_name: str) -> NinResult:
    if not NIN_PATTERN.match(nin):
        raise NinVerificationFailed("NIN must be exactly 11 digits.")
    if not settings.dojah_configured:
        raise NinNotConfigured()

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(
                f"{settings.DOJAH_BASE_URL}/api/v1/kyc/nin",
                params={"nin": nin},
                headers=_headers(),
            )
        except httpx.HTTPError as exc:
            raise NinProviderError() from exc

    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code == 404:
        raise NinVerificationFailed("No record found for that NIN.")
    if res.status_code >= 400:
        raise NinProviderError(body.get("error") or f"NIN lookup failed ({res.status_code})")

    entity = body.get("entity") or {}
    registered_name = " ".join(
        part for part in (entity.get("first_name"), entity.get("last_name")) if part
    ).strip()
    if not registered_name:
        raise NinProviderError("Unexpected response from the identity provider.")
    if not _names_match(registered_name, first_name, last_name):
        raise NinVerificationFailed(
            "The name on this NIN record doesn't match the name you entered."
        )
    return NinResult(registered_name=registered_name, reference=str(entity.get("nin") or nin))
