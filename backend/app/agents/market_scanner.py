"""
MarketScannerAgent — first concrete agent implementation.

Runs weekdays at 18:30 ET (registered in scheduler.py).
For each symbol: fetches price + technicals via yfinance,
builds a Claude analysis prompt (injecting recalled OpenViking context),
stores result in PostgreSQL, and deposits a Case in OpenViking.

Extend store_learnings() to detect and store specific patterns
(e.g. unusual volume, breakouts) as they're identified.
"""
import logging

import anthropic

from app.agents.base import AgentBase
from app.core.config import settings
from app.services import yfinance_service as yf_svc
from app.services.external_api_base import with_retry

logger = logging.getLogger(__name__)

_claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

_SYSTEM_PROMPT = """\
You are a quantitative stock analyst. Analyze the provided market data concisely.
Structure your response as JSON with keys: summary, signals, risk_level, confidence.
- summary: 2-3 sentence plain-English analysis
- signals: list of bullish/bearish signals detected (strings)
- risk_level: "low" | "medium" | "high"
- confidence: float 0.0-1.0
"""


class MarketScannerAgent(AgentBase):
    agent_type = "market_scanner"

    async def fetch_data(self, symbol: str) -> dict:
        info = await yf_svc.get_info(symbol)
        history = await yf_svc.get_history(symbol, period="3mo")

        price = info.get("regularMarketPrice")
        prev_close = info.get("previousClose")
        avg_volume = info.get("averageVolume")
        volume = info.get("volume")

        # Simple technicals from history
        technicals: dict = {}
        if not history.empty:
            closes = history["Close"]
            technicals = {
                "sma_20": round(closes.tail(20).mean(), 2),
                "sma_50": round(closes.tail(50).mean(), 2) if len(closes) >= 50 else None,
                "price_vs_sma20_pct": round(((price or 0) / closes.tail(20).mean() - 1) * 100, 2) if price else None,
                "volume_ratio": round(volume / avg_volume, 2) if volume and avg_volume else None,
            }

        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "change_pct": round(((price / prev_close) - 1) * 100, 2) if price and prev_close else None,
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            **technicals,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]

        context_block = ""
        if prior_context:
            context_block = "\n\nKnowledge base context for this symbol:\n" + "\n".join(
                f"- {p}" for p in prior_context
            )

        user_prompt = f"""
Symbol: {symbol}
Price: ${data.get('price')} ({data.get('change_pct', 0):+.2f}% today)
Sector: {data.get('sector', 'N/A')}
Market Cap: ${data.get('market_cap', 0):,.0f}
Trailing P/E: {data.get('pe_trailing', 'N/A')}
Forward P/E: {data.get('pe_forward', 'N/A')}
SMA20: {data.get('sma_20', 'N/A')} | Price vs SMA20: {data.get('price_vs_sma20_pct', 'N/A')}%
SMA50: {data.get('sma_50', 'N/A')}
Volume ratio (vs 30d avg): {data.get('volume_ratio', 'N/A')}x
{context_block}

Provide a concise market scan analysis. Return valid JSON only.
"""

        def _call_claude() -> dict:
            import json
            message = _claude.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = message.content[0].text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)

        result = await with_retry(_call_claude, label=f"claude.market_scanner({symbol})")
        result["symbol"] = symbol
        result["raw_data"] = data
        return result

    async def store_learnings(self, symbol: str, result: dict) -> None:
        """
        Store analysis summary as Case + detect volume anomalies as Patterns.
        Never raises — all knowledge writes are best-effort.
        """
        # Always store the analysis case
        await self.knowledge.store_analysis_result(
            symbol=symbol,
            summary=result.get("summary", ""),
            agent_type=self.agent_type,
        )

        # Store unusual volume as a pattern
        volume_ratio = result.get("raw_data", {}).get("volume_ratio")
        if volume_ratio and volume_ratio > 2.0:
            await self.knowledge.store_pattern(
                symbol=symbol,
                pattern=f"Volume spike detected: {volume_ratio:.1f}x average. Signals: {result.get('signals', [])}",
                tags=["volume", "anomaly"],
            )
