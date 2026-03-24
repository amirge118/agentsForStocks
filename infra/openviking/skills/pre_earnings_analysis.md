# Skill: Pre-Earnings Analysis

## When to Use
Run this skill 3-7 days before a company's earnings report date.

## Steps

### 1. Confirm earnings date
```python
ticker = yf.Ticker(symbol)
dates = ticker.earnings_dates  # DataFrame with EPS estimate and actual
next_date = dates[dates.index > datetime.now()].index[0]
days_until = (next_date - datetime.now()).days
```
If `days_until > 7` or no upcoming date found, abort — too early for pre-earnings analysis.

### 2. Compute IV percentile
- Get options chain for the nearest expiry after earnings date
- Calculate implied volatility from ATM call/put
- Compare to 30-day historical IV to determine IV rank

### 3. Check analyst consensus
- `info["recommendationMean"]` — 1=Strong Buy, 5=Strong Sell
- `info["numberOfAnalystOpinions"]` — credibility weight (ignore if < 3)
- `info["targetMeanPrice"]` — consensus price target vs current price = implied upside

### 4. Historical earnings surprise rate
- Pull `ticker.earnings` DataFrame
- Calculate beat rate (actual > estimate) over last 8 quarters
- Calculate average surprise magnitude (%)

### 5. Prompt structure for Claude
```
Symbol: {symbol}
Days until earnings: {days_until}
IV rank: {iv_rank:.0f}th percentile
Analyst consensus: {recommendation} ({n_analysts} analysts)
Historical beat rate: {beat_rate:.0%} over last {n_quarters} quarters
Average surprise: {avg_surprise:+.1f}%
Prior context from knowledge base:
{chr(10).join(prior_context)}

Analyze pre-earnings setup. Focus on: risk/reward, positioning implications,
and whether historical patterns support a bullish/bearish/neutral stance.
```

## Known Patterns to Watch For
- IV rank > 80th percentile → options are expensive, selling premium may be favored
- Beat rate > 75% + positive estimate revisions → historically bullish setup
- Beat rate < 40% + negative revisions → historically bearish setup
- Small-cap biotech: standard analysis unreliable — flag for manual review
