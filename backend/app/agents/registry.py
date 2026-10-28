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
    # Reads a company's own reports (10-K, statements, earnings); skipped for funds (ETFs)
    company_only: bool = False


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
        invariants: Iterable[Any] = (),
        profile: Any = None,
        company_only: bool = False,
    ) -> Any:
        """
        invariants: contract rules checked on every result (app/agents/contracts.py).
        profile: the agent's default AgentProfile (app/llm/profiles.py).
        company_only: the agent analyses a company (filings, statements, earnings),
            so it does not run for a fund (ETF) — see app/domain/assets.py.
        """

        def decorator(cls: type[Any]) -> type[Any]:
            if name in self._specs:
                raise ValueError(f"Agent {name!r} registered twice")
            cls.name = name
            cls.invariants = tuple(invariants)
            if profile is not None:
                cls.default_profile = profile
            self._specs[name] = AgentSpec(
                name=name,
                agent_cls=cls,
                description=description,
                depends_on=tuple(depends_on),
                recommendation_weight=recommendation_weight,
                company_only=company_only,
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

    def company_only(self) -> set[str]:
        return {s.name for s in self._specs.values() if s.company_only}

    def downstream(self, names: Iterable[str]) -> set[str]:
        """`names` plus every agent that depends on one of them, directly or not."""
        found = set(names)
        changed = True
        while changed:
            changed = False
            for spec in self._specs.values():
                if spec.name not in found and found.intersection(spec.depends_on):
                    found.add(spec.name)
                    changed = True
        return found

    def execution_levels(
        self, names: Iterable[str] | None = None, *, fund: bool = False
    ) -> list[list[str]]:
        """
        Topologically group agents: every agent appears after all of its dependencies.
        Agents within one level are independent and may run concurrently.
        fund=True leaves out the company-only agents (a fund has no 10-K or earnings).
        """
        selected = set(names) if names is not None else set(self._specs)
        unknown = selected - set(self._specs)
        if unknown:
            raise KeyError(f"Unknown agents: {sorted(unknown)}")
        if fund:
            selected -= self.company_only()

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
