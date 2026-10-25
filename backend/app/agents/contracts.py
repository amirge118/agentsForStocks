"""
Agent contracts — checks that every result is consistent with what the agent
was given and with the rules its prompt states. Applied by AgentRunner after
analyze(), before compliance and storage.

  data_gaps            which inputs were empty (fetched nothing); the prompt is
                       told, and the result records them
  no-data confidence   an agent that received none of its inputs cannot be
                       confident — confidence is capped at NO_DATA_MAX_CONFIDENCE
  invariants           per-agent rules (declared with @register_agent(invariants=…)),
                       e.g. "valuation is only bullish with a margin of safety".
                       A violation does not change the result; it is recorded in
                       result.contract_violations, logged and counted, so prompt
                       or model problems show up in data instead of going unnoticed.
"""

import logging
from collections.abc import Callable, Sized
from dataclasses import fields, is_dataclass
from typing import Any

import pandas as pd

from app.agents.base import AnalysisResult
from app.observability import metrics

logger = logging.getLogger(__name__)

NO_DATA_MAX_CONFIDENCE = 25.0

# (data, result) -> violation message, or None when the rule holds
Invariant = Callable[[Any, AnalysisResult], str | None]


def missing_inputs(data: object) -> list[str]:
    """Names of the inputs that came back empty. A non-dataclass input is one input, "data"."""
    if is_dataclass(data) and not isinstance(data, type):
        return [f.name for f in fields(data) if _is_empty(getattr(data, f.name))]
    return ["data"] if _is_empty(data) else []


def all_inputs(data: object) -> list[str]:
    if is_dataclass(data) and not isinstance(data, type):
        return [f.name for f in fields(data)]
    return ["data"]


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, pd.DataFrame | pd.Series):
        return value.empty
    if isinstance(value, Sized):
        return len(value) == 0
    return False


def apply_contract(
    agent: str, symbol: str, data: object, result: AnalysisResult, invariants: tuple[Invariant, ...]
) -> AnalysisResult:
    gaps = missing_inputs(data)
    violations = [v for check in invariants if (v := check(data, result)) is not None]
    update: dict[str, Any] = {"data_gaps": gaps}

    no_data = bool(gaps) and len(gaps) == len(all_inputs(data))
    if no_data and result.confidence > NO_DATA_MAX_CONFIDENCE:
        violations.append(
            f"judged with no input data at {result.confidence:.0f}% confidence "
            f"(capped at {NO_DATA_MAX_CONFIDENCE:.0f}%)"
        )
        update["confidence"] = NO_DATA_MAX_CONFIDENCE
        update["summary"] = result.summary.replace(
            f"({result.confidence:.0f}%)", f"({NO_DATA_MAX_CONFIDENCE:.0f}%)"
        )

    log_ctx = {"agent": agent, "symbol": symbol}
    if gaps:
        logger.warning("Agent ran with missing inputs", extra={**log_ctx, "data_gaps": gaps})
        metrics.agent_data_gaps.add(1, {"agent": agent})
    for violation in violations:
        logger.warning("Agent contract violated", extra={**log_ctx, "violation": violation})
        metrics.agent_contract_violations.add(1, {"agent": agent})
    update["contract_violations"] = violations
    return result.model_copy(update=update)
