"""create agent_results

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_type", "symbol", "run_date", name="uq_agent_symbol_date"),
    )
    op.create_index("ix_agent_results_agent_type", "agent_results", ["agent_type"])
    op.create_index("ix_agent_results_symbol", "agent_results", ["symbol"])
    op.create_index("ix_agent_results_run_date", "agent_results", ["run_date"])


def downgrade() -> None:
    op.drop_index("ix_agent_results_run_date", table_name="agent_results")
    op.drop_index("ix_agent_results_symbol", table_name="agent_results")
    op.drop_index("ix_agent_results_agent_type", table_name="agent_results")
    op.drop_table("agent_results")
