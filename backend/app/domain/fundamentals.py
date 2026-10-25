"""
Four-factor fundamental scoring with majority vote (adapted from ai-hedge-fund).

Factors: profitability, growth, financial health, valuation. Inputs are the
yfinance Ticker.info dict, whose fields may be missing or None.
"""

from collections import Counter
from dataclasses import dataclass

from app.domain.signals import SignalLabel


@dataclass(frozen=True)
class FactorScore:
    name: str
    signal: SignalLabel
    score: float  # 0-10
    detail: str


@dataclass(frozen=True)
class FundamentalsVote:
    factors: tuple[FactorScore, ...]
    majority: SignalLabel
    agreeing: int
    confidence: float  # share of factors agreeing with the majority, 0-100


def _num(info: dict, key: str, default: float = 0.0) -> float:
    value = info.get(key)
    return float(value) if isinstance(value, int | float) else default


def _fmt_pct(info: dict, key: str) -> str:
    value = info.get(key)
    return f"{value:.1%}" if isinstance(value, int | float) else "N/A"


def _passes_to_factor(name: str, passed: int, detail: str) -> FactorScore:
    """Two or more checks pass → bullish, none → bearish."""
    if passed >= 2:
        return FactorScore(name, "bullish", passed * 3.33, detail)
    if passed == 0:
        return FactorScore(name, "bearish", 1.0, detail)
    return FactorScore(name, "neutral", 5.0, detail)


def score_profitability(info: dict) -> FactorScore:
    """ROE > 15%, net margin > 20%, operating margin > 15%."""
    passed = sum(
        [
            _num(info, "returnOnEquity") > 0.15,
            _num(info, "profitMargins") > 0.20,
            _num(info, "operatingMargins") > 0.15,
        ]
    )
    detail = (
        f"ROE={_fmt_pct(info, 'returnOnEquity')} NM={_fmt_pct(info, 'profitMargins')} "
        f"OM={_fmt_pct(info, 'operatingMargins')}"
    )
    return _passes_to_factor("profitability", passed, detail)


def score_growth(info: dict) -> FactorScore:
    """Revenue growth > 10%, earnings growth > 10%, positive book value."""
    passed = sum(
        [
            _num(info, "revenueGrowth") > 0.10,
            _num(info, "earningsGrowth") > 0.10,
            _num(info, "bookValue") > 0,
        ]
    )
    detail = f"Rev={_fmt_pct(info, 'revenueGrowth')} Earn={_fmt_pct(info, 'earningsGrowth')}"
    return _passes_to_factor("growth", passed, detail)


def score_financial_health(info: dict) -> FactorScore:
    """Current ratio > 1.5, debt/equity < 50% (yfinance reports %), positive FCF."""
    fcf = _num(info, "freeCashflow")
    passed = sum(
        [
            _num(info, "currentRatio") > 1.5,
            _num(info, "debtToEquity", default=999.0) < 50,
            fcf > 0,
        ]
    )
    detail = (
        f"CR={_num(info, 'currentRatio'):.1f} D/E={_num(info, 'debtToEquity'):.0f}% "
        f"FCF={'pos' if fcf > 0 else 'neg'}"
    )
    return _passes_to_factor("financial_health", passed, detail)


def score_valuation(info: dict) -> FactorScore:
    """Expensive when 2+ of P/E > 25, P/B > 3, P/S > 5 (bearish); none → bullish."""
    expensive = sum(
        [
            _num(info, "trailingPE") > 25,
            _num(info, "priceToBook") > 3,
            _num(info, "priceToSalesTrailing12Months") > 5,
        ]
    )
    detail = (
        f"P/E={info.get('trailingPE', 'N/A')} P/B={info.get('priceToBook', 'N/A')} "
        f"P/S={info.get('priceToSalesTrailing12Months', 'N/A')}"
    )
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
    counts = Counter(f.signal for f in factors)
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
