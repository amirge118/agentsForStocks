"""create provider_calls (metered calls per day) and job_runs (scheduled job executions)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_calls",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_id", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_table("provider_calls")
