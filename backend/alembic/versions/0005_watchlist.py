"""watchlist table, seeded once from the WATCHLIST setting

From here on the database is the source of truth for the watchlist; the setting only
provides the initial list, so existing deployments keep the symbols they had.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "watchlist",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    now = datetime.now(UTC)
    # dict.fromkeys drops duplicates while keeping the configured order
    symbols = list(dict.fromkeys(settings.watchlist_symbols))
    if symbols:
        op.bulk_insert(
            table,
            [{"symbol": s, "position": i, "added_at": now} for i, s in enumerate(symbols)],
        )


def downgrade() -> None:
    op.drop_table("watchlist")
