# Skill: Earnings Analysis

Adapted from Anthropic financial-services-plugins earnings framework.

## When to Use
- Post-earnings: within 48 hours of an earnings release
- Pre-earnings: 3-7 days before (use with pre_earnings_analysis skill)
- When user asks "how did X do this quarter?"

## Beat/Miss Framework

### Step 1: Extract actuals vs estimates
```python
# From yfinance
earnings = ticker.quarterly_earnings  # EPS actuals
# Or from news/press release

eps_actual = ...
eps_estimate = ...
rev_actual = ...
rev_estimate = ...

eps_surprise_pct = (eps_actual - eps_estimate) / abs(eps_estimate) * 100
rev_surprise_pct = (rev_actual - rev_estimate) / abs(rev_estimate) * 100
```

### Step 2: Classify beat/miss
| EPS Surprise | Revenue Surprise | Signal |
|---|---|---|
| > +5% | > +3% | Strong Beat → bullish |
| > +2% | any | Moderate Beat → mild bullish |
| -2% to +2% | -2% to +2% | In-line → neutral |
| < -2% | any | Miss → mild bearish |
| < -5% | < -3% | Big Miss → bearish |

### Step 3: Check guidance
Forward guidance > consensus estimate → bullish amplifier
Forward guidance < consensus → bearish amplifier
No guidance change → neutral

### Step 4: Quality check
- Revenue growth: organic vs. acquired?
- Margin expansion: structural or one-time?
- Cash flow: FCF higher or lower than net income? (FCF > NI = quality earnings)
- Share count: dilution vs. buybacks?

## Prompt Template for Claude
```
Symbol: {symbol}  |  Quarter: {quarter}  |  Reported: {date}

Results vs Consensus:
  EPS: ${actual:.2f} vs ${estimate:.2f} ({surprise:+.1f}%)
  Revenue: ${rev_actual:.1f}B vs ${rev_est:.1f}B ({rev_surprise:+.1f}%)
  Operating Margin: {op_margin:.1f}% (prev: {prev_margin:.1f}%)

Guidance: {guidance_summary}

Key metrics:
  FCF: ${fcf:.1f}B  |  Buybacks: ${buybacks:.1f}B  |  Dilution: {shares_change:+.1f}%

Prior knowledge base context:
{prior_context}

Analyze the earnings quality and determine the post-earnings signal.
Focus on: beat quality (one-time vs. structural), guidance credibility,
and whether historical patterns support the reaction.
```

## Common Patterns to Store in OpenViking
After each earnings analysis, store in Memory/Patterns:
- "{SYMBOL} consistently beats EPS by ~{X}% — consensus may be set conservatively"
- "{SYMBOL} Q{N} report: guide-up/guide-down pattern in {year}"
- "{SYMBOL}: FCF typically {X}% above net income — high earnings quality"
