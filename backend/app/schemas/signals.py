"""Signal schemas shared across layers."""

from pydantic import BaseModel, Field

from app.domain.signals import SignalLabel


class LLMSignal(BaseModel):
    """
    The judgement Claude returns for an analyst agent. Only the fields the model
    is asked to produce — the agent attaches everything else.
    """

    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=100.0, description="0-100 confidence score")
    reasoning: str = Field(description="Plain-English explanation of the signal")
