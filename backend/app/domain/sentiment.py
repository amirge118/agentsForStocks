"""Insider-trade scoring and the insider (30%) + news (70%) sentiment blend."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.signals import SignalLabel, direction

INSIDER_WEIGHT = 0.30
NEWS_WEIGHT = 0.70
INSIDER_LOOKBACK_DAYS = 90


@dataclass(frozen=True)
class SentimentScore:
    signal: SignalLabel
    confidence: float  # 0-100
    detail: str


def score_insider_trades(trades: list[dict], now: datetime | None = None) -> SentimentScore:
    """Buy rate over the last 90 days: > 60% bullish, < 30% bearish."""
    if not trades:
        return SentimentScore("neutral", 50.0, "No insider trade data")

    cutoff = (now or datetime.now()) - timedelta(days=INSIDER_LOOKBACK_DAYS)
    buys = sells = 0
    for trade in trades:
        # yfinance column names vary between versions
        tx_type = str(trade.get("Transaction", trade.get("transaction_type", ""))).lower()
        when = trade.get("Start Date", trade.get("filing_date"))
        try:
            if when and datetime.fromisoformat(str(when)[:19]) < cutoff:
                continue
        except ValueError:
            pass
        if "buy" in tx_type or "purchase" in tx_type:
            buys += 1
        elif "sell" in tx_type or "sale" in tx_type:
            sells += 1

    total = buys + sells
    if total == 0:
        return SentimentScore(
            "neutral", 50.0, f"No recent insider trades ({INSIDER_LOOKBACK_DAYS}d)"
        )
    buy_rate = buys / total
    detail = f"buys={buys} sells={sells} ({buy_rate:.0%} buy rate, {INSIDER_LOOKBACK_DAYS}d)"
    if buy_rate > 0.60:
        return SentimentScore("bullish", min(buy_rate * 100, 90.0), detail)
    if buy_rate < 0.30:
        return SentimentScore("bearish", min((1 - buy_rate) * 100, 90.0), detail)
    return SentimentScore("neutral", 50.0, detail)


def headlines(news: list[dict], limit: int = 10) -> list[str]:
    """Non-empty titles from yfinance news items (old and new payload shapes)."""
    titles = []
    for article in news[:limit]:
        content = article.get("content") if isinstance(article.get("content"), dict) else {}
        title = article.get("title") or article.get("headline") or content.get("title")
        if title:
            titles.append(str(title))
    return titles


def blend(insider: SentimentScore, news: SentimentScore) -> SentimentScore:
    combined = (
        direction(insider.signal) * INSIDER_WEIGHT * insider.confidence / 100
        + direction(news.signal) * NEWS_WEIGHT * news.confidence / 100
    )
    if combined > 0.1:
        label: SignalLabel = "bullish"
    elif combined < -0.1:
        label = "bearish"
    else:
        label = "neutral"
    return SentimentScore(
        label, min(abs(combined) * 100 + 40.0, 95.0), f"composite={combined:+.2f}"
    )
