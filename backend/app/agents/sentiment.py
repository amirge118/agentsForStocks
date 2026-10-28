"""SentimentAgent — insider trades (30%) + Claude-classified news headlines (70%)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent
from app.domain.sentiment import SentimentScore, blend, headlines, score_insider_trades
from app.domain.signals import SignalLabel


class ComponentView(BaseModel):
    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=100.0)
    detail: str


class SentimentResult(AnalysisResult):
    insider: ComponentView
    news: ComponentView


@dataclass(frozen=True)
class SentimentData:
    insider_trades: list[dict]
    headlines: list[str]


@register_agent("sentiment", description="Insider trading + news headline sentiment")
class SentimentAgent(Agent[SentimentData, SentimentResult]):
    result_model = SentimentResult

    async def fetch(self, symbol: str, run_date: date) -> SentimentData:
        trades, news = await asyncio.gather(
            self.ctx.yfinance.get_insider_transactions(symbol),
            self.ctx.yfinance.get_news(symbol),
        )
        if not trades:  # Yahoo blocked or empty: the same trades, from the SEC's Form 4s
            trades = await self.ctx.edgar.get_insider_transactions(symbol)
        return SentimentData(insider_trades=trades, headlines=headlines(news))

    async def analyze(self, symbol: str, data: SentimentData, memory: list[str]) -> SentimentResult:
        insider = score_insider_trades(data.insider_trades)
        news = await self._classify_news(symbol, data.headlines)
        combined = blend(insider, news)

        judgement = await self.judge(
            f"""Symbol: {symbol}
Insider trading: {insider.signal} ({insider.confidence:.0f}%) — {insider.detail}
News sentiment:  {news.signal} ({news.confidence:.0f}%) — {news.detail}
Weighted composite (insider 30% / news 70%): {combined.signal} ({combined.confidence:.0f}%)

{knowledge_block(memory)}""",
            fallback=quant_fallback(combined.signal, combined.confidence, "insider/news blend"),
        )
        return SentimentResult.from_judgement(
            "Sentiment",
            judgement,
            insider=ComponentView(**vars(insider)),
            news=ComponentView(**vars(news)),
        )

    async def _classify_news(self, symbol: str, titles: list[str]) -> SentimentScore:
        if not titles:
            return SentimentScore("neutral", 50.0, "No news available")
        bullet_list = "\n".join(f"- {t}" for t in titles)
        unavailable = NewsSentiment(signal="neutral", confidence=50.0, reasoning="unavailable")
        result = await self.ask(
            f"Company: {symbol}\nHeadlines:\n{bullet_list}",
            schema=NewsSentiment,
            fallback=unavailable,
            prompt_name="news_sentiment",
            max_tokens=256,
        )
        if result is unavailable:
            return SentimentScore("neutral", 50.0, "News classification unavailable")
        return SentimentScore(result.signal, result.confidence, f"{len(titles)} headlines analyzed")


class NewsSentiment(BaseModel):
    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str
