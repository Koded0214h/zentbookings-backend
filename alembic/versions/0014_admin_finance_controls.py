"""Add auditable payment adjustments

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_adjustments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("payment_id", sa.String(40), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("provider_reference", sa.String(120), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_payment_adjustments_payment_id", "payment_adjustments", ["payment_id"])
    op.create_index("ix_payment_adjustments_type", "payment_adjustments", ["type"])
    op.create_index("ix_payment_adjustments_status", "payment_adjustments", ["status"])


def downgrade() -> None:
    op.drop_table("payment_adjustments")
