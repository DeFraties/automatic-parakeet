"""setting toggles + leaderboard settings/daily date

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TO_NEW = {"urban_suburban": "suburban,urban", "urban": "urban", "suburban": "suburban"}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    # SQLite doesn't enforce VARCHAR lengths, and rebuilding `games` there would fail once
    # game_rounds rows reference it (foreign keys are on). Only other databases need the ALTER.
    if not _is_sqlite():
        op.alter_column("games", "setting_filter", type_=sa.String(32), existing_type=sa.String(16))
    for old, new in OLD_TO_NEW.items():
        op.execute(
            sa.text(
                "UPDATE games SET setting_filter = :new WHERE setting_filter = :old"
            ).bindparams(new=new, old=old)
        )

    with op.batch_alter_table("leaderboard_entries") as b:
        b.add_column(
            sa.Column("setting_filter", sa.String(32), nullable=False, server_default="rural,urban")
        )
        b.add_column(sa.Column("daily_date", sa.Date(), nullable=True))
        b.drop_index("ix_leaderboard_lookup")
        b.create_index(
            "ix_leaderboard_lookup",
            ["mode", "where_scope", "where_value", "setting_filter", "difficulty", "created_at"],
        )
        b.create_index("ix_leaderboard_daily", ["mode", "daily_date", "difficulty"])


def downgrade() -> None:
    with op.batch_alter_table("leaderboard_entries") as b:
        b.drop_index("ix_leaderboard_daily")
        b.drop_index("ix_leaderboard_lookup")
        b.create_index(
            "ix_leaderboard_lookup",
            ["mode", "where_scope", "where_value", "difficulty", "created_at"],
        )
        b.drop_column("daily_date")
        b.drop_column("setting_filter")
    if not _is_sqlite():
        op.alter_column("games", "setting_filter", type_=sa.String(16), existing_type=sa.String(32))
