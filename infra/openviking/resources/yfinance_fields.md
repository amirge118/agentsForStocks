# yfinance Field Reference

Key fields from `yfinance.Ticker.info` dict. Values can be None if unavailable.

## Price & Market Data
- `regularMarketPrice` — current price (float)
- `previousClose` — previous day close (float)
- `open`, `dayHigh`, `dayLow` — intraday range (float)
- `fiftyTwoWeekHigh`, `fiftyTwoWeekLow` — 52-week range (float)
- `volume`, `averageVolume` — current and 30-day avg (int)
- `marketCap` — total market cap in USD (int)

## Valuation
- `trailingPE`, `forwardPE` — trailing / forward P/E (float)
- `priceToBook` — P/B ratio (float)
- `enterpriseToEbitda` — EV/EBITDA (float)
- `pegRatio` — PEG ratio (float)

## Fundamentals
- `totalRevenue`, `revenueGrowth` — revenue in USD, YoY growth (float)
- `grossMargins`, `operatingMargins`, `profitMargins` — margin ratios (float)
- `returnOnEquity`, `returnOnAssets` — ROE, ROA (float)
- `totalDebt`, `totalCash` — balance sheet items (int)
- `debtToEquity` — D/E ratio (float)
- `freeCashflow` — FCF in USD (int)

## Earnings & Estimates
- `trailingEps`, `forwardEps` — EPS values (float)
- `earningsGrowth` — YoY EPS growth (float)
- `nextFiscalYearEnd` — timestamp (int, convert with datetime.fromtimestamp)
- `mostRecentQuarter` — timestamp of last reported quarter (int)

## Company Info
- `sector`, `industry` — sector/industry classification (str)
- `fullTimeEmployees` — headcount (int)
- `longBusinessSummary` — company description (str)
- `country` — domicile (str)

## Known Quirks
- Fields can be None even for large-cap stocks — always use `.get("field")` not `["field"]`
- `regularMarketPrice` is None for crypto on weekends
- yfinance data has ~15min delay for free users
- `earnings_dates` from `.earnings_dates` property is more reliable than info dict for next earnings
- BRK.B / BRK.A have no standard analyst estimates — skip EPS fields for Berkshire
