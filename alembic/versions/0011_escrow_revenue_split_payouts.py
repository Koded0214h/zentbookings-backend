"""Escrow revenue split and agent payout approval workflow

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escrow_allocations",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("payment_id", sa.String(length=40), nullable=False),
        sa.Column("booking_id", sa.String(length=40), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("gross_amount", sa.Integer(), nullable=False),
        sa.Column("agent_amount", sa.Integer(), nullable=False),
        sa.Column("platform_amount", sa.Integer(), nullable=False),
        sa.Column("agent_percent", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="NGN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index("ix_escrow_allocations_agent_id", "escrow_allocations", ["agent_id"])
    op.create_index("ix_escrow_allocations_booking_id", "escrow_allocations", ["booking_id"])

    op.create_table(
        "payout_requests",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("bank_code", sa.String(length=20), nullable=False),
        sa.Column("bank_name", sa.String(length=120), nullable=False),
        sa.Column("account_number", sa.String(length=20), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("reviewed_by", sa.String(length=40), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.Column("transfer_reference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_reference"),
    )
    op.create_index("ix_payout_requests_agent_id", "payout_requests", ["agent_id"])
    op.create_index("ix_payout_requests_status", "payout_requests", ["status"])
    op.create_index(
        "ix_payout_requests_transfer_reference", "payout_requests", ["transfer_reference"]
    )


def downgrade() -> None:
    op.drop_index("ix_payout_requests_transfer_reference", table_name="payout_requests")
    op.drop_index("ix_payout_requests_status", table_name="payout_requests")
    op.drop_index("ix_payout_requests_agent_id", table_name="payout_requests")
    op.drop_table("payout_requests")
    op.drop_index("ix_escrow_allocations_booking_id", table_name="escrow_allocations")
    op.drop_index("ix_escrow_allocations_agent_id", table_name="escrow_allocations")
    op.drop_table("escrow_allocations")
