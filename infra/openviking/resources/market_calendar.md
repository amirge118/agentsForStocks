# Market Calendar & Schedule Reference

Reference for agents that need to know WHEN to run, WHEN data is stale,
and WHEN to expect unusual market conditions.

## US Market Hours
- **Regular session**: 09:30–16:00 ET, Monday–Friday
- **Pre-market**: 04:00–09:30 ET (lower liquidity, wider spreads)
- **After-hours**: 16:00–20:00 ET (earnings often released here)
- **yfinance data lag**: ~15 minutes during market hours (free tier)

---

## Agent Schedule (all times ET)

| Agent | Time | Why this time |
|---|---|---|
| MarketScanner | 18:30 weekdays | 2.5hrs after close — after-hours price settled |
| Fundamentals | 19:00 weekdays | Fundamentals don't change intraday — once daily is enough |
| Technicals | 19:15 weekdays | Full day's OHLCV available |
| Sentiment | 19:30 weekdays | Evening news cycle captured |
| Valuation | 19:45 weekdays | After all data agents have run |

**Skip conditions**: Do NOT run agents on:
- US market holidays (see list below)
- Days after market circuit breaker triggered
- Weekends (APScheduler `day_of_week="mon-fri"` handles this)

---

## US Market Holidays (NYSE, 2025-2026)

```python
MARKET_HOLIDAYS_2025 = [
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # Martin Luther King Jr. Day
    "2025-02-17",  # Presidents' Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving Day
    "2025-12-25",  # Christmas Day
]

MARKET_HOLIDAYS_2026 = [
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
]
```

---

## Earnings Season Calendar

Earnings are released in 4 quarterly waves:

| Season | Reporting Period | Peak Weeks |
|---|---|---|
| Q4 earnings | Jan–Feb | Mid-Jan to mid-Feb |
| Q1 earnings | Apr–May | Mid-Apr to mid-May |
| Q2 earnings | Jul–Aug | Mid-Jul to mid-Aug |
| Q3 earnings | Oct–Nov | Mid-Oct to mid-Nov |

**EarningsAgent trigger rule**: Run `pre_earnings_analysis` skill when `days_until_earnings ≤ 7`.

```python
import yfinance as yf
from datetime import datetime

def days_until_earnings(symbol: str) -> int | None:
    dates = yf.Ticker(symbol).earnings_dates
    if dates is None or dates.empty:
        return None
    future = dates[dates.index > datetime.now()]
    if future.empty:
        return None
    return (future.index[0] - datetime.now()).days
```

---

## Federal Reserve Calendar (market-moving events)

FOMC meetings (rate decisions) cause high volatility. Run SentimentAgent
with extra weight on news sentiment in the 48hrs around these dates.

2025 FOMC meeting dates (rate decision day):
- Jan 29, Mar 19, May 7, Jun 18, Jul 30, Sep 17, Oct 29, Dec 10

**Agent rule**: If today is within 2 days of FOMC meeting:
- Reduce technicals signal weight (momentum unreliable around Fed days)
- Increase sentiment signal weight
- Flag `"high_macro_risk": true` in result_json

---

## Data Freshness Rules

| Data type | Max age before stale |
|---|---|
| Price / OHLCV | 1 trading day |
| Fundamentals (info dict) | 7 days (updated quarterly) |
| Earnings dates | 7 days |
| Insider trades | 3 days |
| News headlines | 1 day |
| Options chain | 4 hours (intraday) |

If data age exceeds threshold: skip analysis, log warning, do not store result.
