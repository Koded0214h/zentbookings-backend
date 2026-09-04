"""replace link-based email verification with OTP codes

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

Existing users keep whatever is_verified value they already have — this only
changes the flow for new registrations going forward. Nobody already
registered is retroactively locked out.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_email_verification_tokens_user_id", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")

    op.create_table(
        "email_otps",
        sa.Column("user_id", sa.String(length=40), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("email_otps")

    op.create_table(
        "email_verification_tokens",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"]
    )
