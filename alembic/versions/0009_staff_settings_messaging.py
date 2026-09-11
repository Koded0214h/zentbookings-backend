"""Module 5.6-5.7: staff settings, messaging (conversations/messages)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 5.6: staff settings ---
    op.create_table(
        "staff_settings",
        sa.Column("user_id", sa.String(length=40), primary_key=True),
        sa.Column(
            "notify_new_booking", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "notify_new_message", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("payout_bank_code", sa.String(length=20), nullable=True),
        sa.Column("payout_bank_name", sa.String(length=120), nullable=True),
        sa.Column("payout_account_number", sa.String(length=20), nullable=True),
        sa.Column("payout_account_name", sa.String(length=120), nullable=True),
        sa.Column(
            "timezone", sa.String(length=60), nullable=False, server_default="Africa/Lagos"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # --- 5.7: messaging ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=True),
        sa.Column("guest_name", sa.String(length=200), nullable=False),
        sa.Column("guest_email", sa.String(length=255), nullable=False),
        sa.Column("guest_phone", sa.String(length=40), nullable=True),
        sa.Column("guest_token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="OPEN"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_conversations_property_guest", "conversations", ["property_id", "guest_email"]
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index(
        "ix_conversations_guest_token", "conversations", ["guest_token"], unique=True
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("sender_role", sa.String(length=10), nullable=False),
        sa.Column("sender_user_id", sa.String(length=40), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flag_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_guest_token", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_property_guest", table_name="conversations")
    op.drop_table("conversations")

    op.drop_table("staff_settings")
