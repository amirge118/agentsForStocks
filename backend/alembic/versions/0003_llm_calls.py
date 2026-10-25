"""llm_calls ledger + per-run timings and LLM usage on agent_runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run_columns() -> list[sa.Column]:
    return [
        sa.Column("fetch_ms", sa.Integer(), nullable=True),
        sa.Column("analyze_ms", sa.Integer(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("llm_fallbacks", sa.Integer(), nullable=False, server_default="0"),
    ]


_INDEXED = ("created_at", "pipeline_run_id", "run_id", "agent", "model")


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pipeline_run_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_name", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
    )
    for column in _INDEXED:
        op.create_index(f"ix_llm_calls_{column}", "llm_calls", [column])
    for column in _run_columns():
        op.add_column("agent_runs", column)


def downgrade() -> None:
    for column in reversed(_run_columns()):
        op.drop_column("agent_runs", column.name)
    for column in reversed(_INDEXED):
        op.drop_index(f"ix_llm_calls_{column}", table_name="llm_calls")
    op.drop_table("llm_calls")
