from datetime import datetime

import pandas as pd
import pytest

from app.domain.earnings import (
    next_earnings_date,
    post_earnings_reaction,
    surprise_pct,
    surprise_stats,
)
from app.domain.financials import (
    growth_rates,
    liquidity_trend,
    margin_profile,
    yearly_revenue_growth,
)
from app.domain.institutional import flow_direction, net_share_change, top5_concentration
from app.domain.market_scan import scan_metrics
from app.domain.sentiment import SentimentScore, blend, headlines, score_insider_trades


@pytest.mark.unit
def test_growth_and_margins() -> None:
    income = [
        {"revenue": 121, "netIncome": 20, "date": "2025-09-30"},
        {"revenue": 110, "netIncome": 10, "date": "2024-09-30"},
        {"revenue": 100, "netIncome": 5, "date": "2023-09-30"},
    ]
    rates = growth_rates(income, [])
    assert rates.revenue_cagr == pytest.approx(0.10)
    assert rates.fcf_cagr == 0.0
    profile = margin_profile(
        [{"grossProfitMargin": 0.4}, {"grossProfitMargin": 0.42}],
        [{"goodwillAndIntangibleAssets": 25, "totalAssets": 100}],
    )
    assert profile.avg_gross_margin == pytest.approx(0.41)
    assert profile.intangibles_pct == 0.25
    assert margin_profile([], [{"totalAssets": 0}]).intangibles_pct == 0.0
    assert yearly_revenue_growth(income) == [
        ("2025", pytest.approx(0.1)),
        ("2024", pytest.approx(0.1)),
    ]


@pytest.mark.unit
def test_liquidity_trend() -> None:
    assert liquidity_trend([{}]) == "insufficient data"
    improving = [
        {"cashAndCashEquivalents": 20, "totalDebt": 50},
        {"cashAndCashEquivalents": 10, "totalDebt": 100},
    ]
    assert liquidity_trend(improving) == "cash increasing, debt falling"
    worsening = [
        {"cashAndCashEquivalents": 5, "totalDebt": 200},
        {"cashAndCashEquivalents": 10, "totalDebt": 100},
    ]
    assert liquidity_trend(worsening) == "cash declining, debt rising"
    assert liquidity_trend([{"totalDebt": 1}, {"totalDebt": 1}]) == "stable"


@pytest.mark.unit
def test_surprise_stats() -> None:
    surprises = [
        {"epsActual": 1.1, "epsEstimated": 1.0},
        {"epsActual": 0.9, "epsEstimated": 1.0},
        {"epsActual": None, "epsEstimated": 1.0},
        {"epsActual": 1.0, "epsEstimated": 0},
    ]
    stats = surprise_stats(surprises)
    assert (stats.beats, stats.total, stats.beat_rate) == (1, 2, 0.5)
    assert stats.avg_surprise_pct == pytest.approx(0.0)
    assert surprise_pct(None, 1) is None
    assert surprise_stats([]).beat_rate == 0.0


@pytest.mark.unit
def test_post_earnings_reaction_uses_trading_days_after_report() -> None:
    index = pd.bdate_range("2026-01-05", periods=6, tz="America/New_York")
    history = pd.DataFrame({"Close": [100, 110, 100, 100, 121, 121]}, index=index)
    reaction = post_earnings_reaction([{"date": "2026-01-06"}, {"date": None}], history)
    # day0 = Jan 6 (110): +1d → 100, +3d → 121
    assert reaction.avg_1d_return_pct == pytest.approx((100 - 110) / 110 * 100)
    assert reaction.avg_3d_return_pct == pytest.approx((121 - 110) / 110 * 100)
    assert post_earnings_reaction([], history).avg_1d_return_pct == 0.0


@pytest.mark.unit
def test_next_earnings_date_picks_nearest_future_date() -> None:
    """Regression: yfinance lists dates newest-first, so index[0] was the farthest date."""
    index = pd.DatetimeIndex(["2027-01-28", "2026-10-30", "2026-07-30"], tz="UTC")
    dates = pd.DataFrame({"EPS Estimate": [1, 1, 1]}, index=index)
    now = pd.Timestamp("2026-10-25", tz="UTC")
    assert next_earnings_date(dates, now) == "2026-10-30"
    assert next_earnings_date(pd.DataFrame(), now) == "Unknown"
    naive = pd.DataFrame({"x": [1]}, index=pd.DatetimeIndex(["2026-11-01"]))
    assert next_earnings_date(naive, now) == "2026-11-01"
    assert next_earnings_date(dates, pd.Timestamp("2030-01-01", tz="UTC")) == "Unknown"


@pytest.mark.unit
def test_insider_scoring() -> None:
    now = datetime(2026, 10, 25)
    buys = [{"Transaction": "Purchase", "Start Date": "2026-10-01"}] * 4
    sells = [{"Transaction": "Sale", "Start Date": "2026-10-01"}]
    old = [{"Transaction": "Sale", "Start Date": "2025-01-01"}] * 10
    assert score_insider_trades(buys + sells + old, now).signal == "bullish"
    assert score_insider_trades(sells * 5, now).signal == "bearish"
    assert score_insider_trades([], now).detail == "No insider trade data"
    assert score_insider_trades(old, now).signal == "neutral"
    assert (
        score_insider_trades([{"Transaction": "Buy", "Start Date": "bad"}], now).signal == "bullish"
    )


@pytest.mark.unit
def test_headlines_support_both_news_shapes() -> None:
    news = [{"title": "Old shape"}, {"content": {"title": "New shape"}}, {"content": "x"}]
    assert headlines(news) == ["Old shape", "New shape"]


@pytest.mark.unit
def test_sentiment_blend_weights_news_more() -> None:
    insider = SentimentScore("bearish", 90, "")
    news = SentimentScore("bullish", 90, "")
    assert blend(insider, news).signal == "bullish"
    assert (
        blend(SentimentScore("neutral", 50, ""), SentimentScore("neutral", 50, "")).signal
        == "neutral"
    )
    assert (
        blend(SentimentScore("bearish", 90, ""), SentimentScore("bearish", 90, "")).signal
        == "bearish"
    )


@pytest.mark.unit
def test_institutional_metrics() -> None:
    holders = [{"shares": 50, "change": 5}] * 5 + [{"shares": 50, "change": -1}] * 5
    assert net_share_change(holders) == 20
    assert top5_concentration(holders) == 0.5
    assert top5_concentration([]) == 0.0
    assert [flow_direction(x) for x in (1, -1, 0)] == ["accumulating", "distributing", "flat"]


@pytest.mark.unit
def test_scan_metrics() -> None:
    history = pd.DataFrame({"Close": [100.0] * 60})
    info = {
        "regularMarketPrice": 110.0,
        "previousClose": 100.0,
        "volume": 300,
        "averageVolume": 100,
    }
    m = scan_metrics(info, history)
    assert (m.change_pct, m.sma_20, m.sma_50, m.price_vs_sma20_pct) == (10.0, 100.0, 100.0, 10.0)
    assert m.volume_spike
    empty = scan_metrics({}, pd.DataFrame())
    assert empty.sma_20 is None and not empty.volume_spike
