"""create sector_targets (the share of the portfolio wanted in a sector)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sector_targets",
        sa.Column("sector", sa.String(length=64), primary_key=True),
        sa.Column("target_pct", sa.Numeric(5, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sector_targets")
