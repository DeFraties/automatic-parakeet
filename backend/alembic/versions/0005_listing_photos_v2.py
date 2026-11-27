"""spec v2: listing photos (property_images), photo reports, no Google/Mapillary,
urban + rural settings only

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _merge_suburban(value: str) -> str:
    parts = {"urban" if p == "suburban" else p for p in value.split(",") if p}
    return ",".join(sorted(parts)) or "rural,urban"


def upgrade() -> None:
    bind = op.get_bind()

    # --- data: suburban is now part of urban; v2 precision values -------------------------
    op.execute("UPDATE properties SET setting = 'urban' WHERE setting = 'suburban'")
    op.execute(
        "UPDATE properties SET location_precision = 'approximate' "
        "WHERE location_precision IN ('street', 'district')"
    )
    for table in ("games", "leaderboard_entries"):
        rows = bind.execute(sa.text(f"SELECT DISTINCT setting_filter FROM {table}")).fetchall()
        for (old,) in rows:
            new = _merge_suburban(old or "")
            if new != old:
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET setting_filter = :new WHERE setting_filter = :old"
                    ),
                    {"new": new, "old": old},
                )

    # --- properties: v2 columns ------------------------------------------------------------
    op.drop_index("ix_properties_play", table_name="properties")
    with op.batch_alter_table("properties") as b:
        for col in ("pano_id", "sv_status", "image_url", "mly_image_id", "mly_status"):
            b.drop_column(col)
        b.add_column(
            sa.Column("images_status", sa.String(16), nullable=False, server_default="unchecked")
        )
        b.add_column(sa.Column("images_checked_at", sa.DateTime(), nullable=True))
        b.add_column(
            sa.Column(
                "last_seen_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        b.alter_column("lat", existing_type=sa.Float(), nullable=True)
        b.alter_column("lng", existing_type=sa.Float(), nullable=True)
        b.alter_column("location_precision", existing_type=sa.String(16), nullable=True)
    op.create_index(
        "ix_properties_play",
        "properties",
        ["is_active", "images_status", "country_code", "setting"],
    )

    with op.batch_alter_table("sources") as b:
        b.add_column(sa.Column("image_hosts", sa.JSON(), nullable=True))

    op.create_table(
        "property_images",
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("property_id", "position"),
    )
    op.create_table(
        "photo_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.drop_table("sv_usage")

    # --- v2 is listing sites only: retire the non-listing UK Land Registry source ----------
    op.execute(
        "UPDATE properties SET is_active = 0 WHERE source_id IN "
        "(SELECT id FROM sources WHERE key = 'uk_price_paid')"
    )
    op.execute("UPDATE sources SET enabled = 0 WHERE key = 'uk_price_paid'")


def downgrade() -> None:
    op.create_table(
        "sv_usage",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("urls_issued", sa.Integer(), nullable=False),
        sa.Column("daily_reserved_used", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("date"),
    )
    op.drop_table("photo_reports")
    op.drop_table("property_images")
    with op.batch_alter_table("sources") as b:
        b.drop_column("image_hosts")
    op.drop_index("ix_properties_play", table_name="properties")
    with op.batch_alter_table("properties") as b:
        b.drop_column("last_seen_at")
        b.drop_column("images_checked_at")
        b.drop_column("images_status")
        b.add_column(sa.Column("pano_id", sa.String(200), nullable=True))
        b.add_column(sa.Column("sv_status", sa.String(16), nullable=False, server_default="ok"))
        b.add_column(sa.Column("image_url", sa.String(1000), nullable=True))
        b.add_column(sa.Column("mly_image_id", sa.String(64), nullable=True))
        b.add_column(
            sa.Column("mly_status", sa.String(16), nullable=False, server_default="unchecked")
        )
    op.create_index(
        "ix_properties_play",
        "properties",
        ["is_active", "sv_status", "country_code", "setting"],
    )
