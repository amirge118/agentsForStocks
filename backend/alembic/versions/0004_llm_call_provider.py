"""llm_calls.provider — which provider answered each call (for per-provider quotas)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("provider", sa.String(), nullable=True))
    op.create_index("ix_llm_calls_provider", "llm_calls", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_provider", table_name="llm_calls")
    op.drop_column("llm_calls", "provider")
