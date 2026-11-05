"""
LLMReply — a model's validated reply, keyed by a hash of everything that shaped it
(app/llm/replies.py). The same request later reuses it instead of calling the model.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LLMReply(Base):
    __tablename__ = "llm_replies"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<LLMReply {self.prompt_name} {self.key[:8]}>"
