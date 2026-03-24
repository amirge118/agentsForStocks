# Skill: Comparable Company Analysis (Comps)

Adapted from Anthropic financial-services-plugins comps framework.

## When to Use
- Relative valuation: "Is NVDA expensive vs. peers?"
- Sector screening: find the cheapest stock in a sector
- Sanity check on DCF output

## Peer Selection Criteria
Choose 5-8 peers with:
1. Same business model (not just same sector)
2. Similar market cap (±50% preferred, max 3-5x difference)
3. Similar geography (US-listed for US comps)
4. Similar growth profile (±10% revenue growth)

## The 5+5 Rule (from financial-services-plugins)
Maximum 10 metrics total:
- 5 operating metrics: Revenue, Rev Growth%, Gross Margin, EBITDA Margin, FCF Margin
- 5 valuation multiples: EV/Revenue, EV/EBITDA, P/E, P/FCF, PEG

## Data Fetch Pattern
```python
PEER_METRICS = [
    "regularMarketPrice", "marketCap", "enterpriseValue",
    "totalRevenue", "revenueGrowth",
    "grossMargins", "operatingMargins", "ebitdaMargins",
    "trailingPE", "forwardPE", "priceToBook",
    "enterpriseToEbitda", "enterpriseToRevenue",
    "pegRatio", "freeCashflow",
]

peers = {}
for ticker in peer_list:
    info = await get_info(ticker)
    peers[ticker] = {k: info.get(k) for k in PEER_METRICS}
```

## Statistics Block (always include)
For each metric, compute:
- Maximum, 75th percentile, **Median** (primary reference), 25th percentile, Minimum

```python
import numpy as np
values = [p["trailingPE"] for p in peers.values() if p["trailingPE"]]
stats = {
    "max":    np.max(values),
    "p75":    np.percentile(values, 75),
    "median": np.median(values),
    "p25":    np.percentile(values, 25),
    "min":    np.min(values),
}
```

## Relative Valuation Signal
Compare target company to peer median:
- EV/EBITDA < peer median × 0.8 → **bullish** (20%+ discount to peers)
- EV/EBITDA > peer median × 1.2 → **bearish** (20%+ premium to peers)
- Within ±20% of median → **neutral**

Use multiple metrics — at least 3 must agree to generate a signal.

## Output Format
```
TECHNOLOGY COMPS | AAPL • MSFT • GOOGL • META | Q4 2025 | USD Billions

           AAPL   MSFT   GOOGL  META   P75   Median  P25
Rev ($B)   391    245    357    164    357    301     245
Rev Gr%    +6%    +16%   +15%   +19%   +17%   +15%   +11%
EV/EBITDA   25x    28x    20x    22x    27x    23x    21x
P/E         29x    34x    22x    25x    32x    27x    24x
PEG         2.1    1.9    1.4    1.2    2.0    1.7    1.3

Target: {SYMBOL} trades at EV/EBITDA={X}x vs. peer median {M}x ({pct:+.0%})
```

## Patterns to Store in OpenViking
- "Tech sector median EV/EBITDA in Q{N} {year}: {X}x"
- "{SYMBOL} historically trades at {premium/discount}% to {peer} on EV/EBITDA"
