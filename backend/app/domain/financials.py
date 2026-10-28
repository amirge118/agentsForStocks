"""Balance-sheet and multi-year statement metrics (FMP rows, most recent first)."""

from dataclasses import dataclass

from app.domain.stats import cagr, mean, sample_variance

MOAT_KEYWORDS: tuple[str, ...] = (
    "patent",
    "trademark",
    "proprietary",
    "switching cost",
    "network effect",
    "economies of scale",
    "brand",
    "license",
    "regulatory",
    "exclusive",
    "barrier to entry",
    "platform",
    "installed base",
    "recurring revenue",
)

HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "going concern",
    "material weakness",
    "restatement",
    "investigation",
    "litigation",
    "regulatory action",
    "covenant violation",
    "liquidity risk",
    "concentrated customer",
    "single customer",
    "customer concentration",
    "cybersecurity breach",
    "climate risk",
    "geopolitical",
)


@dataclass(frozen=True)
class GrowthRates:
    revenue_cagr: float
    fcf_cagr: float
    net_income_cagr: float


@dataclass(frozen=True)
class MarginProfile:
    avg_gross_margin: float
    gross_margin_variance: float  # lower = more stable pricing power
    intangibles_pct: float  # goodwill + intangibles / total assets


def growth_rates(income: list[dict], cash_flow: list[dict]) -> GrowthRates:
    return GrowthRates(
        revenue_cagr=cagr(income, "revenue"),
        fcf_cagr=cagr(cash_flow, "freeCashFlow"),
        net_income_cagr=cagr(income, "netIncome"),
    )


def margin_profile(ratios: list[dict], balance: list[dict]) -> MarginProfile:
    margins = [r["grossProfitMargin"] for r in ratios if r.get("grossProfitMargin") is not None]
    intangibles_pct = 0.0
    if balance:
        total_assets = balance[0].get("totalAssets") or 0
        if total_assets > 0:
            intangibles_pct = (balance[0].get("goodwillAndIntangibleAssets") or 0) / total_assets
    return MarginProfile(
        avg_gross_margin=mean(margins),
        gross_margin_variance=sample_variance(margins),
        intangibles_pct=intangibles_pct,
    )


def liquidity_trend(balance: list[dict]) -> str:
    """Cash and debt direction between the oldest and newest balance sheet."""
    if len(balance) < 2:
        return "insufficient data"
    newest, oldest = balance[0], balance[-1]
    parts = []
    # A side compares only when both sheets report it: a missing figure is no trend
    cash_new, cash_old = newest.get("cashAndCashEquivalents"), oldest.get("cashAndCashEquivalents")
    if cash_new is not None and cash_old is not None:
        if cash_new > cash_old:
            parts.append("cash increasing")
        elif cash_new < cash_old:
            parts.append("cash declining")
    debt_new, debt_old = newest.get("totalDebt"), oldest.get("totalDebt")
    if debt_new is not None and debt_old is not None:
        if debt_new > debt_old * 1.1:
            parts.append("debt rising")
        elif debt_new < debt_old * 0.9:
            parts.append("debt falling")
    return ", ".join(parts) if parts else "stable"


def yearly_revenue_growth(income: list[dict], years: int = 3) -> list[tuple[str, float]]:
    """[(year, growth vs previous year)] for the most recent `years` years."""
    result = []
    for current, previous in zip(income[:years], income[1 : years + 1], strict=False):
        prev_rev = previous.get("revenue") or 0
        cur_rev = current.get("revenue")
        # A missing year is skipped, not read as revenue falling to 0 (-100%)
        if prev_rev > 0 and cur_rev is not None:
            growth = (cur_rev - prev_rev) / prev_rev
            result.append(((current.get("date") or "?")[:4], growth))
    return result
