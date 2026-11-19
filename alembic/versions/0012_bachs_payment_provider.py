"""Use Bachs as the default payment provider

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("payments", "provider", server_default="bachs", existing_type=sa.String(20))


def downgrade() -> None:
    op.alter_column(
        "payments", "provider", server_default="paystack", existing_type=sa.String(20)
    )
