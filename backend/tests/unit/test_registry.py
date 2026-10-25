import pytest

from app.agents.registry import AgentRegistry


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    for name, deps, weight in [
        ("moat", (), 15),
        ("risk", (), 15),
        ("summary", ("moat", "risk"), 0),
        ("final", ("summary",), 0),
    ]:
        reg.register(name, description=name, depends_on=deps, recommendation_weight=weight)(
            type(name, (), {})
        )
    return reg


@pytest.mark.unit
def test_execution_levels_respect_dependencies() -> None:
    assert _registry().execution_levels() == [["moat", "risk"], ["summary"], ["final"]]


@pytest.mark.unit
def test_execution_levels_for_subset_ignores_unselected_dependencies() -> None:
    assert _registry().execution_levels(["summary", "moat"]) == [["moat"], ["summary"]]


@pytest.mark.unit
def test_unknown_agent_and_cycles_are_rejected() -> None:
    reg = _registry()
    with pytest.raises(KeyError):
        reg.execution_levels(["nope"])

    cyclic = AgentRegistry()
    cyclic.register("a", description="", depends_on=["b"])(type("A", (), {}))
    cyclic.register("b", description="", depends_on=["a"])(type("B", (), {}))
    with pytest.raises(ValueError, match="cycle"):
        cyclic.execution_levels()


@pytest.mark.unit
def test_register_sets_name_and_rejects_duplicates() -> None:
    reg = _registry()
    assert reg.get("moat").agent_cls.name == "moat"
    assert reg.weights() == {"moat": 15, "risk": 15}
    assert reg.names() == ["moat", "risk", "summary", "final"]
    with pytest.raises(ValueError):
        reg.register("moat", description="")(type("Dup", (), {}))
