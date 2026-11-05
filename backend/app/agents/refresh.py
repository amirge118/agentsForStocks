"""
How often each agent really runs on a symbol. While its last result is still good, the
agent doesn't run at all (no data fetched, no model call): the runner copies the stored
result to today, so a quarterly report isn't analysed again every day.

A result stops being good when any of these holds:
  - it is older than max_age_days (0 = run every market day)
  - on_new_report: the company reported earnings since then
  - a person should check it (needs_review), or it had nothing to judge (neutral at 0%
    with empty inputs): tomorrow's data may be better

A daily agent's result stored before that day's close is replaced by the first run after
the close, so a morning run doesn't keep the day's close from being analysed.

`--force` always runs. Override per agent with AGENT_REFRESH, e.g.
AGENT_REFRESH={"moat": {"max_age_days": 30}, "technicals": {"max_age_days": 7}}
"""

import json
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime
from typing import Any

from app.core.clock import market_close, market_today


@dataclass(frozen=True)
class RefreshPolicy:
    max_age_days: int = 0
    on_new_report: bool = False


_REPORTS = 90  # a safety net: a new report normally triggers the run first

DEFAULTS: dict[str, RefreshPolicy] = {
    # Prices and news: new every day
    "technicals": RefreshPolicy(),
    "market_scanner": RefreshPolicy(),
    "sentiment": RefreshPolicy(),
    "valuation": RefreshPolicy(),  # compares its value to today's price
    "outcome_review": RefreshPolicy(),
    "recommendation": RefreshPolicy(),  # reads the agents above
    # Company reports
    "financial_history": RefreshPolicy(_REPORTS, on_new_report=True),
    "moat": RefreshPolicy(_REPORTS, on_new_report=True),
    "earnings": RefreshPolicy(_REPORTS, on_new_report=True),
    "growth": RefreshPolicy(_REPORTS, on_new_report=True),
    # Reports, plus market figures that drift (beta, short ratio, market cap, multiples)
    "risk": RefreshPolicy(30, on_new_report=True),
    "broad_analysis": RefreshPolicy(30, on_new_report=True),
    "fundamentals": RefreshPolicy(7, on_new_report=True),
    # 13F filings come 45 days after each quarter
    "institutional": RefreshPolicy(45),
}


class RefreshBook:
    def __init__(self, overrides: dict[str, dict[str, Any]] | None = None) -> None:
        allowed = {f.name for f in fields(RefreshPolicy)}
        self._policies = dict(DEFAULTS)
        for agent, values in (overrides or {}).items():
            unknown = set(values) - allowed
            if unknown:
                raise ValueError(f"AGENT_REFRESH[{agent}]: unknown settings {sorted(unknown)}")
            self._policies[agent] = replace(self.resolve(agent), **values)

    @classmethod
    def from_config(cls, inline: str = "") -> "RefreshBook":
        return cls(json.loads(inline) if inline.strip() else None)

    def resolve(self, agent: str) -> RefreshPolicy:
        return self._policies.get(agent, RefreshPolicy())


def has_no_evidence(result: dict[str, Any]) -> bool:
    return bool(
        result.get("data_gaps")
        and result.get("signal") == "neutral"
        and not result.get("confidence")
    )


def reusable(policy: RefreshPolicy, result: dict[str, Any], source: date, today: date) -> bool:
    """Everything that can be decided without asking whether a new report came out."""
    if policy.max_age_days <= 0 or (today - source).days > policy.max_age_days:
        return False
    return not result.get("needs_review") and not has_no_evidence(result)


def awaits_the_close(
    policy: RefreshPolicy, stored_at: datetime, run_date: date, now: datetime
) -> bool:
    """A result of today from before the close, for an agent that reads the day's prices."""
    if policy.max_age_days > 0 or run_date != market_today(now):
        return False
    stored = stored_at if stored_at.tzinfo is not None else stored_at.replace(tzinfo=UTC)
    return stored < market_close(run_date) <= now


def latest_report(rows: list[dict[str, Any]]) -> date | None:
    """The newest day a company reported, from earnings rows (epsActual set = reported)."""
    days = [
        str(row["date"])[:10]
        for row in rows
        if row.get("epsActual") is not None and row.get("date")
    ]
    return date.fromisoformat(max(days)) if days else None
