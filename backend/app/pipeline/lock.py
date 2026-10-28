"""
PipelineLock — one pipeline run at a time, across every process.

The daily job (in the worker) and a manual run (from the API) would otherwise
fetch and judge the same symbols twice — idempotent, but double the FMP and LLM
spend — and two workers started by mistake would both run the daily job. On
PostgreSQL the lock is a session advisory lock, held by one connection for the
length of the run and released when it ends (or when the connection dies, so a
crashed process can't leave it stuck). Other databases (SQLite in development
and tests) get an in-process lock: one process, one run.
"""

import asyncio
import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

logger = logging.getLogger(__name__)

# Any constant shared by every process; "AFS" + 1
_KEY = 0x414653_01
_POLL_SECONDS = 15.0


class HeldLock:
    """A lock taken by PipelineLock.acquire(); release it when the run is over."""

    def __init__(self, conn: AsyncConnection | None, local: asyncio.Lock | None) -> None:
        self._conn = conn
        self._local = local

    async def release(self) -> None:
        if self._local is not None:
            self._local.release()
            self._local = None
        if self._conn is not None:
            conn, self._conn = self._conn, None
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _KEY})
                await conn.commit()
            except Exception as exc:  # the lock goes with the connection anyway
                logger.warning("Could not release the pipeline lock", extra={"error": str(exc)})
            finally:
                await conn.close()


class PipelineLock:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        self._poll = poll_seconds
        self._local = asyncio.Lock()
        bind = session_factory.kw.get("bind")
        self._engine: AsyncEngine | None = (
            bind if isinstance(bind, AsyncEngine) and bind.dialect.name == "postgresql" else None
        )

    async def acquire(self, wait_seconds: float = 0.0) -> HeldLock | None:
        """The lock, or None when another run still holds it after `wait_seconds`."""
        if self._engine is None:
            return await self._acquire_local(wait_seconds)
        # Its own connection, kept for the whole run: the lock belongs to it, and
        # committing (no transaction left open for hours) doesn't release it
        conn = await self._engine.connect()
        deadline = time.monotonic() + wait_seconds
        try:
            while True:
                taken = (
                    await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _KEY})
                ).scalar_one()
                await conn.commit()
                if taken:
                    return HeldLock(conn, None)
                if time.monotonic() >= deadline:
                    await conn.close()
                    return None
                await asyncio.sleep(min(self._poll, max(deadline - time.monotonic(), 0)))
        except BaseException:
            await conn.close()
            raise

    async def _acquire_local(self, wait_seconds: float) -> HeldLock | None:
        if self._local.locked() and wait_seconds <= 0:
            return None
        try:
            await asyncio.wait_for(self._local.acquire(), timeout=max(wait_seconds, 0) or None)
        except TimeoutError:
            return None
        return HeldLock(None, self._local)
