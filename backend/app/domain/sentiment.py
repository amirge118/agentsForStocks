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
    """
    Buy rate over the last 90 days: > 60% bullish, < 30% bearish. One decision per
    person, day and direction: a Form 4 reports each price tranche as its own row,
    which would let one large sale outvote several separate purchases.
    """
    if not trades:
        return SentimentScore("neutral", 50.0, "No insider trade data")

    cutoff = (now or datetime.now()) - timedelta(days=INSIDER_LOOKBACK_DAYS)
    buys = sells = 0
    seen: set[tuple[str, str, str]] = set()
    for trade in trades:
        # yfinance columns vary between versions; 1.7 leaves Transaction empty and fills Text
        tx_type = " ".join(
            str(trade.get(column, "")) for column in ("Transaction", "transaction_type", "Text")
        ).lower()
        when = trade.get("Start Date", trade.get("filing_date"))
        try:
            if when and datetime.fromisoformat(str(when)[:19]) < cutoff:
                continue
        except ValueError:
            pass
        is_buy = "buy" in tx_type or "purchase" in tx_type
        if not is_buy and "sell" not in tx_type and "sale" not in tx_type:
            continue
        insider = str(trade.get("Insider") or "").strip().lower()
        if insider:  # Without a name, separate rows can't be told to be one decision
            event = (insider, str(when)[:10], "buy" if is_buy else "sell")
            if event in seen:
                continue
            seen.add(event)
        if is_buy:
            buys += 1
        else:
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
