"""create decision_outcomes (forward returns of each decision, per horizon)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXED = ("symbol", "decision_date", "status")


def upgrade() -> None:
    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("benchmark", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("raw_return", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "symbol", "decision_date", "horizon_days", name="uq_outcome_symbol_date_horizon"
        ),
    )
    for column in _INDEXED:
        op.create_index(f"ix_decision_outcomes_{column}", "decision_outcomes", [column])


def downgrade() -> None:
    for column in reversed(_INDEXED):
        op.drop_index(f"ix_decision_outcomes_{column}", table_name="decision_outcomes")
    op.drop_table("decision_outcomes")
