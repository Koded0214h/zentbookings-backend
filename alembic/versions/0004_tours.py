"""tour booking + per-property schedules

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_schedules",
        sa.Column("property_id", sa.Integer(), primary_key=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Africa/Lagos"),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("capacity_per_slot", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("auto_confirm", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("advance_booking_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("min_notice_hours", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("weekly_hours", sa.JSON(), nullable=False),
        sa.Column("blackout_dates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "tours",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=True),
        sa.Column("visitor_name", sa.String(length=200), nullable=False),
        sa.Column("visitor_email", sa.String(length=255), nullable=False),
        sa.Column("visitor_phone", sa.String(length=40), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("confirmation_code", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tours_property_slot", "tours", ["property_id", "scheduled_at"])
    op.create_index("ix_tours_user_id", "tours", ["user_id"])
    op.create_index("ix_tours_visitor_email", "tours", ["visitor_email"])
    op.create_index("ix_tours_confirmation_code", "tours", ["confirmation_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tours_confirmation_code", table_name="tours")
    op.drop_index("ix_tours_visitor_email", table_name="tours")
    op.drop_index("ix_tours_user_id", table_name="tours")
    op.drop_index("ix_tours_property_slot", table_name="tours")
    op.drop_table("tours")
    op.drop_table("property_schedules")
