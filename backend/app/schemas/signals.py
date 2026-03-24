"""
Signal schemas — shared Pydantic models used by all analyst agents.
Every agent produces an AnalystSignal. The signal_aggregator combines them
into a ConsolidatedSignal per symbol.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalystSignal(BaseModel):
    """Output of a single analyst agent for one symbol."""
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=100.0, description="0-100 confidence score")
    reasoning: str = Field(description="Plain-English explanation of the signal")
    agent_type: str
    symbol: str


class SubSignal(BaseModel):
    """A component signal within a multi-factor agent."""
    name: str
    signal: Literal["bullish", "bearish", "neutral"]
    score: float = Field(ge=0.0, le=10.0, description="0-10 sub-score")
    detail: str = ""


class ConsolidatedSignal(BaseModel):
    """
    Aggregated result across multiple analyst agents for one symbol.
    Produced by signal_aggregator.py.
    """
    symbol: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=100.0)
    bullish_count: int
    bearish_count: int
    neutral_count: int
    agent_signals: list[AnalystSignal]
    reasoning: str


class PortfolioDecision(BaseModel):
    """Trading decision produced by the portfolio manager (future)."""
    symbol: str
    action: Literal["buy", "sell", "hold", "short", "cover"]
    quantity: int = 0
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str
    max_position_value: float = 0.0
