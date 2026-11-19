from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.payment_providers import bachs
from app.services.payment_providers.base import PaymentProvider


def get_payment_provider() -> PaymentProvider:
    if settings.PAYMENT_PROVIDER == "bachs":
        return bachs.provider
    raise AppError(
        503,
        "payment_provider_not_configured",
        f"Unsupported payment provider: {settings.PAYMENT_PROVIDER}",
    )


__all__ = ["get_payment_provider"]
