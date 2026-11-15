"""
SectorTarget — the share of the portfolio wanted in one sector, in percent. Targets don't
have to add up to 100: a sector without one is simply not compared.
"""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SectorTarget(Base):
    __tablename__ = "sector_targets"

    sector: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    def __repr__(self) -> str:
        return f"<SectorTarget {self.sector}: {self.target_pct}%>"
