from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.knowledge.openviking_store import OpenVikingStore
from app.knowledge.store import Learning, NullKnowledgeStore


@pytest.mark.unit
async def test_null_store_is_a_no_op() -> None:
    store = NullKnowledgeStore()
    assert await store.recall("AAPL", "moat") == []
    await store.store("AAPL", "moat", Learning(kind="case", content="x"))


def _store_with(client: MagicMock) -> OpenVikingStore:
    store = OpenVikingStore(url="http://ov", api_key=None)
    store._client = client
    return store


@pytest.mark.unit
async def test_recall_filters_by_relevance_score() -> None:
    client = MagicMock()
    client.find.return_value = SimpleNamespace(
        resources=[
            SimpleNamespace(abstract="relevant", snippet="", score=0.9),
            SimpleNamespace(abstract=None, snippet="weak", score=0.2),
        ]
    )
    assert await _store_with(client).recall("AAPL", "moat") == ["relevant"]


@pytest.mark.unit
async def test_store_routes_cases_and_patterns_to_their_uris() -> None:
    client = MagicMock()
    store = _store_with(client)
    await store.store("AAPL", "moat", Learning(kind="case", content="summary"))
    await store.store("AAPL", "moat", Learning(kind="pattern", content="p", tags=("moat",)))
    await store.store("AAPL", "moat", Learning(kind="case", content=""))  # empty → skipped

    uris = [call.kwargs["uri"] for call in client.add_resource.call_args_list]
    assert uris == [
        "viking://agent/memories/cases/moat/AAPL/",
        "viking://agent/memories/patterns/AAPL/",
    ]
    assert client.add_resource.call_args_list[1].kwargs["metadata"]["tags"] == [
        "AAPL",
        "moat",
        "pattern",
        "moat",
    ]


@pytest.mark.unit
async def test_failures_are_swallowed() -> None:
    client = MagicMock()
    client.find.side_effect = RuntimeError("down")
    client.add_resource.side_effect = RuntimeError("down")
    store = _store_with(client)
    assert await store.recall("AAPL", "moat") == []
    await store.store("AAPL", "moat", Learning(kind="case", content="x"))
