"""property: dedicated type column, amenity search, created_by, soft delete

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("type", sa.String(length=20), nullable=True))
    op.add_column(
        "properties",
        sa.Column("amenities_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "properties", sa.Column("created_by_id", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "properties", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_properties_created_by", "properties", "users", ["created_by_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_properties_type", "properties", ["type"])
    op.create_index("ix_properties_deleted_at", "properties", ["deleted_at"])

    # --- backfill (Postgres) ---
    op.execute(
        "UPDATE properties SET type = "
        "CASE WHEN period = 'Per Night' THEN 'Nightly' ELSE 'Monthly' END "
        "WHERE type IS NULL"
    )
    op.execute(
        "UPDATE properties SET amenities_text = COALESCE("
        "(SELECT lower(string_agg(v, ' | ')) "
        " FROM json_array_elements_text(amenities::json) AS v), '')"
    )

    op.alter_column("properties", "type", nullable=False)
    op.alter_column("properties", "amenities_text", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_properties_deleted_at", table_name="properties")
    op.drop_index("ix_properties_type", table_name="properties")
    op.drop_constraint("fk_properties_created_by", "properties", type_="foreignkey")
    op.drop_column("properties", "deleted_at")
    op.drop_column("properties", "created_by_id")
    op.drop_column("properties", "amenities_text")
    op.drop_column("properties", "type")
