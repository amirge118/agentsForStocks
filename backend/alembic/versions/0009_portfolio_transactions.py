"""create portfolio_transactions (the portfolio ledger)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.create_table(
        "portfolio_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=True),
        sa.Column("shares", _MONEY, nullable=True),
        sa.Column("price", _MONEY, nullable=True),
        sa.Column("fee", _MONEY, nullable=False),
        sa.Column("amount", _MONEY, nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_portfolio_transactions_trade_date", "portfolio_transactions", ["trade_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_transactions_trade_date", table_name="portfolio_transactions")
    op.drop_table("portfolio_transactions")
