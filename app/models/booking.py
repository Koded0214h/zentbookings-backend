from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin, _utcnow, gen_id

BOOKING_STATUSES = ("PENDING_PAYMENT", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED")
ACTIVE_BOOKING_STATUSES = ("CONFIRMED", "ACTIVE")  # these actually block a date range
PAYMENT_STATUSES = ("PENDING", "SUCCESS", "FAILED")
PAYMENT_ADJUSTMENT_TYPES = ("REFUND", "CHARGEBACK")
PAYMENT_ADJUSTMENT_STATUSES = ("PENDING", "COMPLETED", "FAILED", "CANCELLED")
WALLET_TX_TYPES = ("CREDIT", "DEBIT", "REFUND")
PAYOUT_STATUSES = ("PENDING", "APPROVED", "DISBURSED", "REJECTED", "FAILED")


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_property_dates", "property_id", "check_in", "check_out"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("bkg"))
    property_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    guest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    guest_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    guest_phone: Mapped[str] = mapped_column(String(40), nullable=False)

    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    guests: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    price_per_night: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaning_fee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    security_deposit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_fee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="PENDING_PAYMENT", nullable=False)
    confirmation_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("pay"))
    booking_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), default="bachs", nullable=False)
    reference: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaymentAdjustment(TimestampMixin, Base):
    """Auditable refund/chargeback record.

    Provider-side refunds are deliberately not implied by this row. An admin records
    the provider reference and marks the adjustment complete only after the money has
    actually moved.
    """

    __tablename__ = "payment_adjustments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("adj"))
    payment_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("payments.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Wallet(Base):
    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class WalletTransaction(TimestampMixin, Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("wtx"))
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    booking_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # CREDIT | DEBIT
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EscrowAllocation(TimestampMixin, Base):
    """Immutable revenue split captured when a provider charge settles."""

    __tablename__ = "escrow_allocations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("esc"))
    payment_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("payments.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    booking_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    gross_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_fee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agent_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)


class PayoutRequest(TimestampMixin, Base):
    __tablename__ = "payout_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: gen_id("pot"))
    agent_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True, nullable=False)
    bank_code: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transfer_reference: Mapped[str | None] = mapped_column(
        String(120), unique=True, index=True, nullable=True
    )
