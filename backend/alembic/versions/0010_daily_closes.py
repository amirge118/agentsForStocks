"""create daily_closes (finished sessions' closes, fetched once)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_closes",
        sa.Column("symbol", sa.String(length=10), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_closes")
