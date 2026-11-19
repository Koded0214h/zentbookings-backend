"""NIN (Nigerian National Identity Number) verification via Ninja.

Used once, at agent sign-up: the applicant submits their NIN alongside the
usual registration fields, we verify it with Ninja, and the account is
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


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.NINJA_SECRET_KEY or ''}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    if settings.NINJA_BASE_URL:
        return settings.NINJA_BASE_URL.rstrip("/")
    key = settings.NINJA_SECRET_KEY or ""
    if key.startswith("sk_sandbox_"):
        return "https://api.sandbox.ninja.boucloud.io"
    return "https://api.ninja.boucloud.io"


async def verify_nin(nin: str, *, first_name: str, last_name: str) -> NinResult:
    if not NIN_PATTERN.match(nin):
        raise NinVerificationFailed("NIN must be exactly 11 digits.")
    if not settings.ninja_configured:
        raise NinNotConfigured()

    payload = {
        "idType": "nin",
        "mode": "verify",
        "idNumber": nin,
        "firstName": first_name.strip(),
        "lastName": last_name.strip(),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.post(
                f"{_base_url()}/api/identity/identify",
                headers=_headers(),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise NinProviderError() from exc

    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code == 404:
        raise NinVerificationFailed("No record found for that NIN.")
    if res.status_code >= 400:
        message = body.get("message") if isinstance(body, dict) else None
        raise NinProviderError(message or f"NIN verification failed ({res.status_code})")
    if not isinstance(body, dict):
        raise NinProviderError("Unexpected response from the identity provider.")
    if body.get("found") is False:
        raise NinVerificationFailed("No record found for that NIN.")
    if body.get("verified") is not True or body.get("recommendation") != "accept":
        raise NinVerificationFailed(
            "The name on this NIN record doesn't match the name you entered."
        )
    registered_name = f"{first_name.strip()} {last_name.strip()}"
    reference = body.get("request_id") or body.get("requestId") or ""
    return NinResult(registered_name=registered_name, reference=str(reference))
