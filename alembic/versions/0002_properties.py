"""property catalogue

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("image", sa.String(length=1024), nullable=False),
        sa.Column("gallery", sa.JSON(), nullable=False),
        sa.Column("beds", sa.Integer(), nullable=False),
        sa.Column("baths", sa.Integer(), nullable=False),
        sa.Column("sqft", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("year_built", sa.Integer(), nullable=False),
        sa.Column("amenities", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("full_description", sa.Text(), nullable=False),
        sa.Column("dot_color", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_properties_location", "properties", ["location"])
    op.create_index("ix_properties_price", "properties", ["price"])
    op.create_index("ix_properties_category", "properties", ["category"])


def downgrade() -> None:
    op.drop_index("ix_properties_category", table_name="properties")
    op.drop_index("ix_properties_price", table_name="properties")
    op.drop_index("ix_properties_location", table_name="properties")
    op.drop_table("properties")
