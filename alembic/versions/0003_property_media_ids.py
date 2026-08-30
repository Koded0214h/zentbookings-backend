"""property cloudinary public-id bookkeeping

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "properties", sa.Column("image_public_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "properties",
        sa.Column(
            "gallery_public_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column("properties", "gallery_public_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("properties", "gallery_public_ids")
    op.drop_column("properties", "image_public_id")
