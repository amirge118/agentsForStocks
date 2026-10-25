"""
Agent registry — agents register themselves with @register_agent, and everything
else (pipeline order, recommendation weights, API metadata) is derived from it.

Adding an agent = one new module with a decorated class. No scheduler edits.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentSpec:
    name: str
    agent_cls: type[Any]
    description: str
    depends_on: tuple[str, ...]
    # Weight in the final recommendation score; 0 = informational only
    recommendation_weight: float


class AgentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        depends_on: Iterable[str] = (),
        recommendation_weight: float = 0.0,
    ) -> Any:
        def decorator(cls: type[Any]) -> type[Any]:
            if name in self._specs:
                raise ValueError(f"Agent {name!r} registered twice")
            cls.name = name
            self._specs[name] = AgentSpec(
                name=name,
                agent_cls=cls,
                description=description,
                depends_on=tuple(depends_on),
                recommendation_weight=recommendation_weight,
            )
            return cls

        return decorator

    def get(self, name: str) -> AgentSpec:
        return self._specs[name]

    def all(self) -> list[AgentSpec]:
        return list(self._specs.values())

    def names(self) -> list[str]:
        return list(self._specs)

    def weights(self) -> dict[str, float]:
        return {
            s.name: s.recommendation_weight for s in self._specs.values() if s.recommendation_weight
        }

    def execution_levels(self, names: Iterable[str] | None = None) -> list[list[str]]:
        """
        Topologically group agents: every agent appears after all of its dependencies.
        Agents within one level are independent and may run concurrently.
        """
        selected = set(names) if names is not None else set(self._specs)
        unknown = selected - set(self._specs)
        if unknown:
            raise KeyError(f"Unknown agents: {sorted(unknown)}")

        remaining = {n: set(self._specs[n].depends_on) & selected for n in selected}
        levels: list[list[str]] = []
        while remaining:
            ready = sorted(n for n, deps in remaining.items() if not deps)
            if not ready:
                raise ValueError(f"Dependency cycle between agents: {sorted(remaining)}")
            levels.append(ready)
            for n in ready:
                del remaining[n]
            for deps in remaining.values():
                deps.difference_update(ready)
        return levels


registry = AgentRegistry()
register_agent = registry.register
