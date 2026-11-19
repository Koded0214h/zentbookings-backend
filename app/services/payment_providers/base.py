from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    kind: str
    reference: str | None
    data: dict


class PaymentProvider(Protocol):
    name: str

    async def initialize_payment(
        self,
        *,
        email: str,
        name: str,
        phone: str,
        amount_naira: int,
        reference: str,
        callback_url: str,
        metadata: dict | None = None,
    ) -> dict: ...

    async def verify_payment(self, provider_id: str) -> dict: ...

    def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> ProviderEvent: ...

    async def disburse_to_bank(
        self,
        *,
        amount_naira: int,
        account_name: str,
        account_number: str,
        bank_code: str,
        reference: str,
        reason: str,
    ) -> dict: ...
