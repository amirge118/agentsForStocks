import pytest

from app.db import session as db


@pytest.mark.unit
def test_engine_options_skip_pool_settings_for_sqlite() -> None:
    assert db._engine_options("sqlite+aiosqlite:///:memory:") == {}
    assert db._engine_options("postgresql+asyncpg://x/y")["pool_size"] == 10


@pytest.mark.unit
async def test_get_db_session_commits_and_rolls_back(monkeypatch, session_factory) -> None:
    monkeypatch.setattr(db, "AsyncSessionLocal", session_factory)

    gen = db.get_db_session()
    session = await gen.__anext__()
    assert session.is_active
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

    gen = db.get_db_session()
    await gen.__anext__()
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("handler failed"))
