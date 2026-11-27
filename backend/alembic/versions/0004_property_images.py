"""property images: listing photo URL + Mapillary image

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMNs: no table rebuild, safe on SQLite with existing games.
    op.add_column("properties", sa.Column("image_url", sa.String(1000), nullable=True))
    op.add_column("properties", sa.Column("mly_image_id", sa.String(64), nullable=True))
    op.add_column(
        "properties",
        sa.Column("mly_status", sa.String(16), nullable=False, server_default="unchecked"),
    )


def downgrade() -> None:
    with op.batch_alter_table("properties") as b:
        b.drop_column("mly_status")
        b.drop_column("mly_image_id")
        b.drop_column("image_url")
