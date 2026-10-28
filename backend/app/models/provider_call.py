"""
ProviderCall — calls made to a metered data provider per market day (FMP's free
plan allows 250). Kept in the database so a restart, or a second process, can't
reset the count and overrun the plan.
"""

from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProviderCall(Base):
    __tablename__ = "provider_calls"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ProviderCall {self.provider} {self.day}: {self.calls}>"
