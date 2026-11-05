"""create llm_replies (reusable model replies) and agent_runs.llm_reused

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_replies",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("prompt_name", sa.String(length=64), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("llm_reused", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "llm_reused")
    op.drop_table("llm_replies")
