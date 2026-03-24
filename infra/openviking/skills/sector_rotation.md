# Skill: Sector Rotation Analysis

## When to Use
Run weekly (Monday pre-market) to detect capital rotation between sectors.
Use alongside individual stock analysis to add macro context.

## Market Cycle → Sector Mapping

| Cycle Phase | Outperforming Sectors | Underperforming |
|---|---|---|
| Early expansion | Financials, Consumer Discretionary, Industrials | Utilities, Consumer Staples |
| Mid expansion | Technology, Industrials, Materials | Utilities |
| Late expansion | Energy, Materials, Consumer Staples | Tech, Consumer Discretionary |
| Recession | Utilities, Consumer Staples, Healthcare | Financials, Industrials |
| Early recovery | Financials, Consumer Discretionary | Energy, Utilities |

## Computation Steps

### 1. Fetch sector ETF prices
```python
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
# Fetch 3-month history for all ETFs
```

### 2. Calculate relative strength vs SPY
```python
spy_return = (spy_history["Close"].iloc[-1] / spy_history["Close"].iloc[0]) - 1
for sector, etf in SECTOR_ETFS.items():
    etf_return = (etf_history["Close"].iloc[-1] / etf_history["Close"].iloc[0]) - 1
    relative_strength[sector] = etf_return - spy_return
```

### 3. Rank sectors by RS score
- Top 3 = strong rotation into these sectors
- Bottom 3 = capital flowing out

### 4. Detect regime change
Compare current top-3 to last week's top-3.
If ≥2 sectors changed → flag as rotation event (high significance).

### 5. Prompt structure for Claude
```
Current sector RS ranking (3-month, vs SPY):
{ranked_sectors}

Previous week ranking: {prior_ranking}
Rotation detected: {yes/no} — {changed_sectors}

Prior context from knowledge base:
{chr(10).join(prior_context)}

Analyze sector rotation. Identify the likely market cycle phase,
which individual stocks in rotating sectors to watch,
and implications for the current watchlist: {watchlist_symbols}.
```

## Known Patterns
- Energy/Materials outperforming simultaneously often signals late-cycle inflation trade
- XLU leading for 3+ consecutive weeks = defensive rotation, recession signal
- XLK + XLC leading together = risk-on, growth-favored environment
