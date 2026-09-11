"""Module 5.1-5.4: listing detail fields, bookings, payments, wallet

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 5.1: listing detail fields on properties ---
    op.add_column("properties", sa.Column("street_address", sa.String(length=255), nullable=True))
    op.add_column("properties", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("properties", sa.Column("state_region", sa.String(length=120), nullable=True))
    op.add_column("properties", sa.Column("zip_code", sa.String(length=20), nullable=True))
    op.add_column("properties", sa.Column("country", sa.String(length=120), nullable=True))
    op.add_column(
        "properties",
        sa.Column("cleaning_fee", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "properties",
        sa.Column("security_deposit", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "properties",
        sa.Column("minimum_stay_nights", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "properties",
        sa.Column(
            "cancellation_policy", sa.String(length=30), nullable=False, server_default="Flexible"
        ),
    )
    op.add_column("properties", sa.Column("check_in_time", sa.String(length=5), nullable=True))
    op.add_column("properties", sa.Column("check_out_time", sa.String(length=5), nullable=True))
    op.add_column(
        "properties",
        sa.Column("max_guests", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "properties",
        sa.Column("pets_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for col in (
        "cleaning_fee",
        "security_deposit",
        "minimum_stay_nights",
        "cancellation_policy",
        "max_guests",
        "pets_allowed",
    ):
        op.alter_column("properties", col, server_default=None)

    # --- 5.2: bookings ---
    op.create_table(
        "bookings",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=True),
        sa.Column("guest_name", sa.String(length=200), nullable=False),
        sa.Column("guest_email", sa.String(length=255), nullable=False),
        sa.Column("guest_phone", sa.String(length=40), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=False),
        sa.Column("guests", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price_per_night", sa.Integer(), nullable=False),
        sa.Column("cleaning_fee", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("security_deposit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING_PAYMENT"),
        sa.Column("confirmation_code", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_bookings_property_dates", "bookings", ["property_id", "check_in", "check_out"]
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_guest_email", "bookings", ["guest_email"])
    op.create_index(
        "ix_bookings_confirmation_code", "bookings", ["confirmation_code"], unique=True
    )

    # --- 5.3: payments ---
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("booking_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="paystack"),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])
    op.create_index("ix_payments_reference", "payments", ["reference"], unique=True)

    # --- 5.4: wallet ---
    op.create_table(
        "wallets",
        sa.Column("user_id", sa.String(length=40), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="NGN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("booking_id", sa.String(length=40), nullable=True),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_wallet_transactions_user_id", "wallet_transactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_user_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_table("wallets")

    op.drop_index("ix_payments_reference", table_name="payments")
    op.drop_index("ix_payments_booking_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_bookings_confirmation_code", table_name="bookings")
    op.drop_index("ix_bookings_guest_email", table_name="bookings")
    op.drop_index("ix_bookings_user_id", table_name="bookings")
    op.drop_index("ix_bookings_property_dates", table_name="bookings")
    op.drop_table("bookings")

    for col in (
        "pets_allowed",
        "max_guests",
        "check_out_time",
        "check_in_time",
        "cancellation_policy",
        "minimum_stay_nights",
        "security_deposit",
        "cleaning_fee",
        "country",
        "zip_code",
        "state_region",
        "city",
        "street_address",
    ):
        op.drop_column("properties", col)
