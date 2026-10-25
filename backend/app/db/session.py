"""
Async SQLAlchemy engine and session factory.
Use get_db_session() as a FastAPI dependency — it yields an AsyncSession
and commits/rolls back automatically.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _engine_options(url: str) -> dict[str, Any]:
    # Connection-pool sizing only applies to server databases; SQLite (tests) has no pool
    if url.startswith("sqlite"):
        return {}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


engine = create_async_engine(
    settings.database_url, echo=False, **_engine_options(settings.database_url)
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Yields an AsyncSession and handles commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
