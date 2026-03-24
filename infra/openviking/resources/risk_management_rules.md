# Risk Management Rules

Hard rules enforced by risk_service.py and the PortfolioManagerAgent.
These are constraints, not suggestions. Never override them in agent logic.

## Position Sizing Rules

### Volatility Regimes (annualized)
| Regime | Threshold | Max Allocation | Notes |
|---|---|---|---|
| Low | < 15% | 25% | Stable blue-chips (JNJ, PG, KO) |
| Medium | 15-30% | 20% | Most S&P 500 stocks |
| High | 30-50% | 12% | Growth stocks, small-caps |
| Very High | > 50% | 8% | Biotech, meme stocks, crypto-adjacent |

### Correlation Adjustments
| Correlation to portfolio | Multiplier | Effect |
|---|---|---|
| ≥ 0.80 (very high) | 0.70× | Reduce by 30% |
| 0.60-0.80 (high) | 0.85× | Reduce by 15% |
| 0.40-0.60 (moderate) | 1.00× | No change |
| 0.20-0.40 (low) | 1.05× | Slight increase |
| < 0.20 (very low) | 1.10× | Small diversification bonus |

**Hard cap**: No single position > 25% of portfolio regardless of correlation.

---

## Portfolio-Level Constraints

### Cash Buffer
- Minimum 20% cash at all times — liquidity reserve
- During high-VIX environments (VIX > 30): raise to 35% cash
- Never deploy full cash on a single signal

### Sector Concentration
- No single sector > 40% of portfolio
- Technology sector special rule: max 35% (historically most concentrated risk)
- If sector approaches limit: reduce position sizes in new trades, not existing

### Diversification Minimums
- Minimum 5 positions for a "live" portfolio
- Avoid > 3 positions in same sub-industry (e.g., 3 semiconductor stocks max)

---

## Signal Thresholds for Action

| Signal Strength | Action |
|---|---|
| Consolidated confidence ≥ 65%, bullish | Consider buy |
| Consolidated confidence ≥ 65%, bearish | Consider sell/reduce |
| Consolidated confidence < 65% | **Hold — do nothing** |
| Single agent signal only (no consolidation) | **Never act** |
| Valuation agent = bearish (any confidence) | Override bullish signals — caution |

**Hold is always valid.** Overtrading is the primary risk in algorithmic systems.

---

## Stop-Loss / Drawdown Rules

- Individual position loss > 20%: flag for review, do not auto-sell
- Individual position loss > 35%: reduce by 50% regardless of current signal
- Portfolio drawdown > 15% from high: reduce all positions by 25%, raise cash
- Portfolio drawdown > 25%: halt all new buy signals until recovery > 10%

---

## Risk Signals That Override Everything

These conditions trigger automatic hold/reduce regardless of analyst signals:

1. **Earnings in < 3 days**: hold unless EarningsAgent has run
2. **VIX > 35**: reduce all new positions by 50%
3. **Market circuit breaker triggered**: no new positions for 5 trading days
4. **API data gap > 2 days**: mark data as stale, hold all positions
5. **Agent confidence average < 40%** across all agents for a symbol: neutral/hold only

---

## Position Sizing Formula

```python
def size_position(portfolio_value, risk_pct, stop_loss_pct):
    """
    Kelly-inspired position sizing.
    risk_pct: how much of portfolio you're willing to lose on this trade (e.g., 0.02 = 2%)
    stop_loss_pct: distance to stop loss (e.g., 0.10 = 10% below entry)
    """
    max_loss_dollars = portfolio_value * risk_pct
    position_size = max_loss_dollars / stop_loss_pct
    return min(position_size, portfolio_value * 0.25)  # hard cap at 25%

# Example: $100k portfolio, risk 2%, stop 10% below entry
# position = ($100k × 0.02) / 0.10 = $20,000 max
```
