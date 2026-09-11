from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import EmailStr, Field, field_serializer

from app.schemas.common import CamelModel

Status = Literal["PENDING_PAYMENT", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"]


def _iso_z(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class BookingCreate(CamelModel):
    property_id: int
    guest_name: str | None = Field(default=None, max_length=200)
    guest_email: EmailStr | None = None
    guest_phone: str | None = Field(default=None, max_length=40)
    check_in: date
    check_out: date
    guests: int = Field(default=1, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=2000)
    # where Paystack sends the browser back after checkout; defaults to FRONTEND_BASE_URL
    redirect_url: str | None = None


class BookingOut(CamelModel):
    id: str
    property_id: int
    user_id: str | None = None
    guest_name: str
    guest_email: EmailStr
    guest_phone: str
    check_in: date
    check_out: date
    nights: int
    guests: int
    price_per_night: int
    cleaning_fee: int
    security_deposit: int
    subtotal: int
    total_amount: int
    currency: str
    status: Status
    confirmation_code: str
    notes: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at", when_used="json")
    def _ser_created(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class PaymentInit(CamelModel):
    authorization_url: str
    reference: str


class BookingCreateResponse(CamelModel):
    booking: BookingOut
    payment: PaymentInit


class BookingListResponse(CamelModel):
    bookings: list[BookingOut]
    total: int
    page: int
    limit: int
    total_pages: int


class GuestBookingAction(CamelModel):
    confirmation_code: str = Field(min_length=1)
    email: EmailStr


class BlockedRange(CamelModel):
    check_in: date
    check_out: date


class BlockedDatesResponse(CamelModel):
    property_id: int
    ranges: list[BlockedRange]


class WalletTransactionOut(CamelModel):
    id: str
    type: Literal["CREDIT", "DEBIT"]
    amount: int
    balance_after: int
    booking_id: str | None = None
    note: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at", when_used="json")
    def _ser_created(self, v: datetime | None) -> str | None:
        return _iso_z(v)


class WalletOut(CamelModel):
    balance: int
    currency: str
    transactions: list[WalletTransactionOut]
