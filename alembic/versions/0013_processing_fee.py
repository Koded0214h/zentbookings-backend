"""Add explicit booking processing fee

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("processing_fee", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "escrow_allocations",
        sa.Column("processing_fee", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("escrow_allocations", "processing_fee")
    op.drop_column("bookings", "processing_fee")
