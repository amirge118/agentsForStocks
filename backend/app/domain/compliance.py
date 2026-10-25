"""
Compliance — rule-based review of client-facing recommendation text.

Rules adapted from the SEC Marketing Rule / antifraud checklist in the
"Claude for Financial Advisors" plugin (Apache-2.0):
  - No promissory or absolute language ("guaranteed", "risk-free", ...)  → fail
  - No exaggerated / hype claims ("can't miss", "to the moon", ...)       → flag
  - A bullish call must mention risk or limitations (fair and balanced)   → flag
Every recommendation carries a standard disclaimer.

Deterministic on purpose: no LLM call, so re-runs give identical results.
"""

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["flag", "fail"]
Status = Literal["pass", "flag", "fail"]

DISCLAIMER = (
    "This is an automated analysis for informational purposes only and is not "
    "investment advice. All investing involves risk, including possible loss of "
    "principal. Past performance is not a guarantee of future results."
)

# Promissory / absolute claims — never allowed in a recommendation
_PROMISSORY = [
    r"guarantee[ds]?",
    r"assured?",
    r"promise[ds]?",
    r"risk[- ]free",
    r"no risk",
    r"can(?:'|no)t lose",
    r"cannot lose",
    r"sure thing",
    r"certain to",
    r"will definitely",
]

# Exaggerated / unwarranted claims — allowed only after rewording
_EXAGGERATED = [
    r"can(?:'|no)t miss",
    r"no[- ]brainer",
    r"to the moon",
    r"once[- ]in[- ]a[- ]lifetime",
    r"skyrocket(?:s|ing)?",
    r"explode(?:s)? higher",
]

# Words that negate a promissory term right before it ("not guaranteed")
_NEGATIONS = ("not", "no", "never", "isn't", "without")

_RISK_TERMS = re.compile(
    r"\b(risk|risks|risky|downside|volatil\w*|uncertain\w*|headwind\w*|"
    r"concern\w*|leverage|debt|valuation|competition|drawdown)\b",
    re.IGNORECASE,
)

_PROMISSORY_RE = [re.compile(rf"\b{p}\b", re.IGNORECASE) for p in _PROMISSORY]
_EXAGGERATED_RE = [re.compile(rf"\b{p}\b", re.IGNORECASE) for p in _EXAGGERATED]


@dataclass(frozen=True)
class ComplianceFinding:
    rule: str
    severity: Severity
    phrase: str


@dataclass(frozen=True)
class ComplianceReview:
    status: Status
    findings: tuple[ComplianceFinding, ...]


def review_recommendation(text: str, signal: str) -> ComplianceReview:
    """Review recommendation text. signal is "bullish" | "bearish" | "neutral"."""
    findings: list[ComplianceFinding] = []

    for pattern in _PROMISSORY_RE:
        for match in pattern.finditer(text):
            if not _is_negated(text, match.start()):
                findings.append(ComplianceFinding("promissory_language", "fail", match.group()))

    for pattern in _EXAGGERATED_RE:
        for match in pattern.finditer(text):
            findings.append(ComplianceFinding("exaggerated_claim", "flag", match.group()))

    if signal == "bullish" and not _RISK_TERMS.search(text):
        findings.append(ComplianceFinding("missing_risk_discussion", "flag", ""))

    if any(f.severity == "fail" for f in findings):
        status: Status = "fail"
    elif findings:
        status = "flag"
    else:
        status = "pass"
    return ComplianceReview(status=status, findings=tuple(findings))


def _is_negated(text: str, start: int) -> bool:
    preceding = text[:start].split()
    return bool(preceding) and preceding[-1].lower() in _NEGATIONS
