"""Agent sign-up: NIN verification fields on users

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nin", sa.String(length=11), nullable=True))
    op.add_column(
        "users",
        sa.Column("nin_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("nin_verified_name", sa.String(length=200), nullable=True))
    op.alter_column("users", "nin_verified", server_default=None)
    op.create_unique_constraint("uq_users_nin", "users", ["nin"])


def downgrade() -> None:
    op.drop_constraint("uq_users_nin", "users", type_="unique")
    op.drop_column("users", "nin_verified_name")
    op.drop_column("users", "nin_verified")
    op.drop_column("users", "nin")
