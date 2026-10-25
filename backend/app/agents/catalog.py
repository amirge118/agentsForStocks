"""
Importing this module registers every agent. Add new agent modules here.
Everything else discovers agents through app.agents.registry.
"""

from app.agents import (  # noqa: F401 — imported for their @register_agent side effect
    broad_analysis,
    earnings,
    financial_history,
    fundamentals,
    growth,
    institutional,
    market_scanner,
    moat,
    recommendation,
    risk,
    sentiment,
    technicals,
    valuation,
)
from app.agents.registry import AgentRegistry, registry


def load_agents() -> AgentRegistry:
    return registry
