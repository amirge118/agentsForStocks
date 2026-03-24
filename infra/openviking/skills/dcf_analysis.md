# Skill: DCF Analysis (Bear/Base/Bull)

Adapted from Anthropic financial-services-plugins DCF framework.

## When to Use
When ValuationAgent needs to build or explain a DCF model for a stock.
Also use when a user asks "what is this stock worth?" or "is it undervalued?"

## Three Scenarios

| Parameter | Bear | Base | Bull |
|---|---|---|---|
| Stage 1 growth (5yr) | 3% | 7% | 12% |
| Stage 2 growth (5yr) | 2% | 4% | 6% |
| Terminal growth | 2.0% | 2.5% | 3.0% |
| WACC | 12% | 10% | 9% |
| Margin of safety haircut | 15% | 15% | 15% |

## Steps

### 1. Get base FCF
```python
fcf = info.get("freeCashflow")
# Fallback if FCF negative or missing:
fcf = info.get("operatingIncome") * 0.75
```

### 2. Two-stage DCF formula
```python
def dcf_value(fcf, g1, g2, terminal_g, wacc, years1=5, years2=5):
    pv = 0
    cf = fcf
    for t in range(1, years1+1):
        cf *= (1 + g1)
        pv += cf / (1+wacc)**t
    for t in range(years1+1, years1+years2+1):
        cf *= (1 + g2)
        pv += cf / (1+wacc)**t
    terminal = cf * (1+terminal_g) / (wacc - terminal_g)
    pv += terminal / (1+wacc)**(years1+years2)
    return pv * 0.85  # 15% haircut
```

### 3. Signal mapping
- Intrinsic value > market cap by >20% → **bullish** (margin of safety)
- Market cap > intrinsic value by >20% → **bearish** (overvalued)
- Within ±20% → **neutral**

## WACC Sanity Checks
- WACC must be > terminal growth rate (or formula breaks)
- Typical WACC range: 8-15% for public equities
- Terminal growth should not exceed long-run GDP growth (2.5-3%)

## Terminal Value Warning
Terminal value typically = 50-70% of total EV. If it exceeds 80%, the model
is too sensitive to terminal assumptions — flag for manual review.

## Sensitivity Table (5x5)
Always check: WACC (±100bp in each direction) × Terminal Growth (±50bp)
```
        TG=1.5%  TG=2.0%  TG=2.5%  TG=3.0%  TG=3.5%
WACC=8%   ...
WACC=9%
WACC=10%  ← Base
WACC=11%
WACC=12%  ← Bear
```
