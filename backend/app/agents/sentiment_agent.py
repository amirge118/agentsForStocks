"""
SentimentAgent — insider trading (30%) + news sentiment (70%) weighted signal.
Adapted from virattt/ai-hedge-fund sentiment.py.

Data sources:
  - Insider trades: from yfinance .get_insider_transactions()
  - News sentiment: from yfinance .get_news(), analyzed by Claude if no pre-computed score

Weights: insider=30%, news=70%
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import llm_service
from app.services import yfinance_service as yf_svc
from app.services.external_api_base import with_retry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a market sentiment analyst. You receive insider trading and news sentiment data.
Return JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100), reasoning (string, max 200 chars).
"""

_NEWS_SENTIMENT_PROMPT = """\
Classify the sentiment of these news headlines for {symbol} as bullish, bearish, or neutral.
Return JSON: {{"sentiment": "bullish"|"bearish"|"neutral", "confidence": 0-100}}
Headlines:
{headlines}
"""


class SentimentAgent(AgentBase):
    agent_type = "sentiment"

    async def fetch_data(self, symbol: str) -> dict:
        import yfinance as yf
        from app.services.external_api_base import with_retry

        def _get_insider():
            ticker = yf.Ticker(symbol)
            try:
                df = ticker.get_insider_transactions()
                return df.to_dict("records") if df is not None and not df.empty else []
            except Exception:
                return []

        def _get_news():
            ticker = yf.Ticker(symbol)
            try:
                news = ticker.get_news(count=20)
                return news if news else []
            except Exception:
                return []

        insider_trades = await with_retry(_get_insider, label=f"yfinance.insider({symbol})")
        news = await with_retry(_get_news, label=f"yfinance.news({symbol})")

        return {"symbol": symbol, "insider_trades": insider_trades, "news": news}

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]

        insider_signal, insider_conf, insider_detail = _score_insider(data["insider_trades"])
        news_signal, news_conf, news_detail = await _score_news(symbol, data["news"])

        # Weighted combination
        def sig_to_val(s: str) -> float:
            return {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}[s]

        combined = (
            sig_to_val(insider_signal) * 0.30 * (insider_conf / 100) +
            sig_to_val(news_signal) * 0.70 * (news_conf / 100)
        )
        overall_signal = "bullish" if combined > 0.1 else "bearish" if combined < -0.1 else "neutral"
        overall_conf = min(abs(combined) * 100 + 40.0, 95.0)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"
        user_prompt = f"""
Symbol: {symbol}
Insider trading: {insider_signal} (conf={insider_conf:.0f}%) — {insider_detail}
News sentiment:  {news_signal} (conf={news_conf:.0f}%) — {news_detail}
Weighted composite: {overall_signal} ({overall_conf:.0f}%)
Prior knowledge base context: {context_str}

Produce the final signal JSON.
"""
        result = await llm_service.call_claude(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AnalystSignal,
        )

        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "insider": {"signal": insider_signal, "confidence": insider_conf, "detail": insider_detail},
            "news": {"signal": news_signal, "confidence": news_conf, "detail": news_detail},
            "summary": f"Sentiment: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------

def _score_insider(trades: list[dict]) -> tuple[str, float, str]:
    """Classify insider trades as bullish/bearish. Returns (signal, confidence, detail)."""
    if not trades:
        return "neutral", 50.0, "No insider trade data"

    cutoff = datetime.now() - timedelta(days=90)
    buys = 0
    sells = 0

    for t in trades:
        # yfinance insider transaction columns vary — try common names
        tx_type = str(t.get("Transaction", t.get("transaction_type", ""))).lower()
        date_val = t.get("Start Date", t.get("filing_date", None))
        try:
            if date_val and datetime.fromisoformat(str(date_val)) < cutoff:
                continue
        except (ValueError, TypeError):
            pass

        if "buy" in tx_type or "purchase" in tx_type:
            buys += 1
        elif "sell" in tx_type or "sale" in tx_type:
            sells += 1

    total = buys + sells
    if total == 0:
        return "neutral", 50.0, "No recent insider trades (90d)"

    buy_rate = buys / total
    detail = f"buys={buys} sells={sells} ({buy_rate:.0%} buy rate, 90d)"

    if buy_rate > 0.60:
        return "bullish", min(buy_rate * 100, 90.0), detail
    if buy_rate < 0.30:
        return "bearish", min((1 - buy_rate) * 100, 90.0), detail
    return "neutral", 50.0, detail


async def _score_news(symbol: str, news: list[dict]) -> tuple[str, float, str]:
    """Score news headlines. Returns (signal, confidence, detail)."""
    if not news:
        return "neutral", 50.0, "No news available"

    headlines = []
    for article in news[:10]:
        title = article.get("title", article.get("headline", ""))
        if title:
            headlines.append(title)

    if not headlines:
        return "neutral", 50.0, "No usable headlines"

    prompt = _NEWS_SENTIMENT_PROMPT.format(
        symbol=symbol,
        headlines="\n".join(f"- {h}" for h in headlines),
    )

    result = await llm_service.call_claude(
        system_prompt="You are a financial news sentiment classifier. Return only JSON.",
        user_prompt=prompt,
        max_tokens=128,
    )

    sentiment = str(result.get("sentiment", "neutral"))
    confidence = float(result.get("confidence", 50.0))
    detail = f"{len(headlines)} headlines analyzed"

    return sentiment, confidence, detail
