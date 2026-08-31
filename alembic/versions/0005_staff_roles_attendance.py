"""staff roles, attendance, audit, agent profiles, lead status

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users: login & presence ---
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_ip", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("last_login_method", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    # --- tours: lead pipeline ---
    op.add_column(
        "tours",
        sa.Column("lead_status", sa.String(length=20), nullable=False, server_default="NEW"),
    )
    op.alter_column("tours", "lead_status", server_default=None)

    # --- property <-> agent assignment ---
    op.create_table(
        "property_agents",
        sa.Column("property_id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.String(length=40), primary_key=True),
        sa.Column("assigned_by", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
    )

    # --- staff attendance ---
    op.create_table(
        "staff_attendance",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="web"),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("auto_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_staff_attendance_user_id", "staff_attendance", ["user_id"])
    op.create_index(
        "ix_staff_attendance_user_open", "staff_attendance", ["user_id", "clock_out_at"]
    )

    # --- audit log ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=40), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_action", "audit_log", ["action"])
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id"])

    # --- agent public profiles ---
    op.create_table(
        "agent_profiles",
        sa.Column("user_id", sa.String(length=40), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("linkedin_url", sa.String(length=400), nullable=True),
        sa.Column("headshot_url", sa.String(length=1024), nullable=True),
        sa.Column("headshot_public_id", sa.String(length=255), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("agent_profiles")
    op.drop_index("ix_audit_target", table_name="audit_log")
    op.drop_index("ix_audit_action", table_name="audit_log")
    op.drop_index("ix_audit_actor_user_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_staff_attendance_user_open", table_name="staff_attendance")
    op.drop_index("ix_staff_attendance_user_id", table_name="staff_attendance")
    op.drop_table("staff_attendance")
    op.drop_table("property_agents")
    op.drop_column("tours", "lead_status")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "last_login_method")
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
