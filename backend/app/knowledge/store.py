"""KnowledgeStore protocol + the no-op implementation used when OpenViking is disabled."""

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class Learning:
    """Something an agent wants remembered. 'case' = run summary, 'pattern' = recurring signal."""

    kind: Literal["case", "pattern"]
    content: str
    tags: tuple[str, ...] = field(default_factory=tuple)


class KnowledgeStore(Protocol):
    async def recall(self, symbol: str, agent_type: str) -> list[str]:
        """Plain-text observations relevant to this symbol + agent. [] on any failure."""
        ...

    async def store(self, symbol: str, agent_type: str, learning: Learning) -> None:
        """Persist a learning. Must never raise."""
        ...

    async def ping(self) -> None:
        """Raise when the store can't be reached. Unlike recall, it doesn't hide the failure."""
        ...


class NullKnowledgeStore:
    async def recall(self, symbol: str, agent_type: str) -> list[str]:
        return []

    async def ping(self) -> None:
        return None

    async def store(self, symbol: str, agent_type: str, learning: Learning) -> None:
        return None
