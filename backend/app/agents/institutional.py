"""InstitutionalAgent — smart-money accumulation or distribution from 13F data (FMP + yfinance)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import knowledge_block, num, pct
from app.agents.registry import register_agent
from app.domain.institutional import (
    FlowDirection,
    flow_direction,
    net_share_change,
    top5_concentration,
)
from app.knowledge.store import Learning


class InstitutionalResult(AnalysisResult):
    # None: not reported (no holder rows, no ownership figure) — never 0 for unknown
    institutional_pct: float | None
    net_share_change: float | None
    direction: FlowDirection
    top5_concentration: float | None


@dataclass(frozen=True)
class InstitutionalData:
    holders: list[dict]
    ownership_trend: list[dict]
    info: dict


@register_agent(
    "institutional",
    description="Institutional ownership trend (13F)",
    recommendation_weight=5,
    company_only=True,
)
class InstitutionalAgent(Agent[InstitutionalData, InstitutionalResult]):
    result_model = InstitutionalResult

    async def fetch(self, symbol: str, run_date: date) -> InstitutionalData:
        holders, trend, info = await asyncio.gather(
            self.ctx.fmp.get_institutional_holders(symbol),
            self.ctx.fmp.get_13f_institutional_ownership(symbol, limit=4),
            self.ctx.yfinance.get_info(symbol),
        )
        return InstitutionalData(holders=holders, ownership_trend=trend, info=info)

    async def analyze(
        self, symbol: str, data: InstitutionalData, memory: list[str]
    ) -> InstitutionalResult:
        held = data.info.get("heldPercentInstitutions")
        inst_pct = float(held) if isinstance(held, int | float) else None
        net_change = net_share_change(data.holders)
        concentration = top5_concentration(data.holders)
        direction = flow_direction(net_change)

        judgement = await self.judge(
            f"""Symbol: {symbol}

Institutional ownership: {pct(inst_pct)} of shares outstanding
Net change across top holders: {num(net_change, "+,.0f")} shares ({direction})
Top-5 holder concentration: {pct(concentration)} of institutional holdings

Top institutional holders:
{_format_holders(data.holders)}

Quarterly 13F ownership trend:
{_format_trend(data.ownership_trend)}

{knowledge_block(memory)}""",
            fallback=neutral_fallback(),
        )
        return InstitutionalResult.from_judgement(
            "Institutional",
            judgement,
            detail=f"{direction}",
            institutional_pct=inst_pct,
            net_share_change=net_change,
            direction=direction,
            top5_concentration=concentration,
        )

    def learnings(self, symbol: str, result: InstitutionalResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        if result.direction in ("accumulating", "distributing"):
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Institutions {result.direction} — net change "
                    f"{num(result.net_share_change, '+,.0f')} shares",
                    tags=("institutional", "smart_money"),
                )
            )
        return learnings


def _format_holders(holders: list[dict]) -> str:
    if not holders:
        return "No holder data available."
    lines = ["Holder | Shares | Change"]
    for h in holders[:10]:
        lines.append(
            f"{(h.get('holder') or 'Unknown')[:30]} | {h.get('shares') or 0:,.0f} | "
            f"{h.get('change') or 0:+,.0f}"
        )
    return "\n".join(lines)


def _format_trend(trend: list[dict]) -> str:
    if not trend:
        return "No 13F trend data available."
    lines = ["Date | Investor | Shares | Change"]
    for t in trend[:8]:
        lines.append(
            f"{str(t.get('date') or '?')[:10]} | {(t.get('investorName') or 'Unknown')[:30]} | "
            f"{t.get('sharesNumber') or 0:,.0f} | {t.get('changeInSharesNumber') or 0:+,.0f}"
        )
    return "\n".join(lines)
