"""
Four-factor fundamental scoring with majority vote (adapted from ai-hedge-fund).

Factors: profitability, growth, financial health, valuation. Inputs are the
yfinance Ticker.info dict, whose fields may be missing or None.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.signals import SignalLabel


@dataclass(frozen=True)
class FactorScore:
    name: str
    signal: SignalLabel
    score: float  # 0-10
    detail: str
    has_data: bool = True  # False: every field behind the factor was missing


@dataclass(frozen=True)
class FundamentalsVote:
    factors: tuple[FactorScore, ...]
    majority: SignalLabel
    agreeing: int
    confidence: float  # share of factors agreeing with the majority, 0-100


Check = tuple[str, Callable[[float], bool]]


def _value(info: dict, key: str) -> float | None:
    value = info.get(key)
    return float(value) if isinstance(value, int | float) else None


def _fmt_pct(info: dict, key: str) -> str:
    value = info.get(key)
    return f"{value:.1%}" if isinstance(value, int | float) else "N/A"


def _run_checks(info: dict, checks: list[Check]) -> tuple[int, int]:
    """(checks passed, checks with data). A missing field is no evidence either way."""
    values = [(_value(info, key), test) for key, test in checks]
    known = [(v, test) for v, test in values if v is not None]
    return sum(test(v) for v, test in known), len(known)


def _no_data(name: str, detail: str) -> FactorScore:
    return FactorScore(name, "neutral", 5.0, f"{detail} (no data)", has_data=False)


def _passes_to_factor(name: str, passed: int, known: int, detail: str) -> FactorScore:
    """Two or more checks pass → bullish, none of the known ones → bearish."""
    if known == 0:
        return _no_data(name, detail)
    if passed >= 2:
        return FactorScore(name, "bullish", passed * 3.33, detail)
    if passed == 0:
        return FactorScore(name, "bearish", 1.0, detail)
    return FactorScore(name, "neutral", 5.0, detail)


def score_profitability(info: dict) -> FactorScore:
    """ROE > 15%, net margin > 20%, operating margin > 15%."""
    passed, known = _run_checks(
        info,
        [
            ("returnOnEquity", lambda v: v > 0.15),
            ("profitMargins", lambda v: v > 0.20),
            ("operatingMargins", lambda v: v > 0.15),
        ],
    )
    detail = (
        f"ROE={_fmt_pct(info, 'returnOnEquity')} NM={_fmt_pct(info, 'profitMargins')} "
        f"OM={_fmt_pct(info, 'operatingMargins')}"
    )
    return _passes_to_factor("profitability", passed, known, detail)


def score_growth(info: dict) -> FactorScore:
    """Revenue growth > 10%, earnings growth > 10%, positive book value."""
    passed, known = _run_checks(
        info,
        [
            ("revenueGrowth", lambda v: v > 0.10),
            ("earningsGrowth", lambda v: v > 0.10),
            ("bookValue", lambda v: v > 0),
        ],
    )
    detail = f"Rev={_fmt_pct(info, 'revenueGrowth')} Earn={_fmt_pct(info, 'earningsGrowth')}"
    return _passes_to_factor("growth", passed, known, detail)


def score_financial_health(info: dict) -> FactorScore:
    """Current ratio > 1.5, debt/equity < 50% (yfinance reports %), positive FCF."""
    passed, known = _run_checks(
        info,
        [
            ("currentRatio", lambda v: v > 1.5),
            ("debtToEquity", lambda v: v < 50),
            ("freeCashflow", lambda v: v > 0),
        ],
    )
    cr, de, fcf = (_value(info, k) for k in ("currentRatio", "debtToEquity", "freeCashflow"))
    detail = (
        f"CR={'N/A' if cr is None else f'{cr:.1f}'} "
        f"D/E={'N/A' if de is None else f'{de:.0f}%'} "
        f"FCF={'N/A' if fcf is None else ('pos' if fcf > 0 else 'neg')}"
    )
    return _passes_to_factor("financial_health", passed, known, detail)


def score_valuation(info: dict) -> FactorScore:
    """Expensive when 2+ of P/E > 25, P/B > 3, P/S > 5 (bearish); none of the known → bullish."""
    expensive, known = _run_checks(
        info,
        [
            ("trailingPE", lambda v: v > 25),
            ("priceToBook", lambda v: v > 3),
            ("priceToSalesTrailing12Months", lambda v: v > 5),
        ],
    )
    detail = (
        f"P/E={info.get('trailingPE', 'N/A')} P/B={info.get('priceToBook', 'N/A')} "
        f"P/S={info.get('priceToSalesTrailing12Months', 'N/A')}"
    )
    if known == 0:  # no multiple at all is not "cheap"
        return _no_data("valuation", detail)
    if expensive >= 2:
        return FactorScore("valuation", "bearish", 2.0, detail)
    if expensive == 0:
        return FactorScore("valuation", "bullish", 8.0, detail)
    return FactorScore("valuation", "neutral", 5.0, detail)


def vote(info: dict) -> FundamentalsVote:
    factors = (
        score_profitability(info),
        score_growth(info),
        score_financial_health(info),
        score_valuation(info),
    )
    # Only factors with data vote; confidence is still out of all four, so missing
    # data lowers it (no data at all → neutral at 0%)
    counts = Counter(f.signal for f in factors if f.has_data)
    bullish, bearish, neutral = counts["bullish"], counts["bearish"], counts["neutral"]
    if bullish > bearish and bullish > neutral:
        majority: SignalLabel = "bullish"
    elif bearish > bullish and bearish > neutral:
        majority = "bearish"
    else:
        majority = "neutral"
    agreeing = max(bullish, bearish, neutral)
    return FundamentalsVote(
        factors=factors,
        majority=majority,
        agreeing=agreeing,
        confidence=agreeing / len(factors) * 100.0,
    )
