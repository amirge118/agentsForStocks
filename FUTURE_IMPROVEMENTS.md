# Future Improvements

Add ideas and "nice to haves" discovered during implementation here.
Format: `- [ ] Description [PRIORITY: HIGH / MED / LOW]`

## Agents
- [ ] Add EarningsAgent — specialized pre/post earnings analysis with IV rank (see skills/earnings_analysis.md) [PRIORITY: HIGH]
- [ ] Add PortfolioHealthAgent — portfolio-level risk scoring and rebalancing signals [PRIORITY: HIGH]
- [ ] Add SectorTrendAgent — sector rotation detection using ETF relative strength (see skills/sector_rotation.md) [PRIORITY: MED]
- [ ] Add PortfolioManagerAgent — aggregates all agent signals → buy/sell/hold decisions (adapted from ai-hedge-fund portfolio_manager.py) [PRIORITY: HIGH]
- [ ] Add personality agents (Warren Buffett, Charlie Munger style) using ai-hedge-fund patterns [PRIORITY: LOW]
- [ ] Add CompsAgent — comparable company analysis (see skills/comparable_companies.md) [PRIORITY: MED]
- [ ] Agent retry queue — if yfinance is down, queue the run for 30min later [PRIORITY: MED]
- [ ] Run all 5 agents in parallel per symbol using signal_aggregator.run_all_agents() [PRIORITY: HIGH]

## Knowledge Layer (OpenViking)
- [ ] Auto-detect and store "anomaly" patterns when analysis result deviates >2σ from historical [PRIORITY: MED]
- [ ] Dashboard to browse knowledge base (list patterns/cases per symbol) [PRIORITY: LOW]
- [ ] Knowledge quality scoring — track which recalled patterns improved analysis accuracy [PRIORITY: LOW]
- [ ] Periodic knowledge pruning — archive cases older than 2 years [PRIORITY: LOW]

## Data
- [ ] Add Alpha Vantage as fallback data source when yfinance is unavailable [PRIORITY: MED]
- [ ] Cache yfinance responses in Redis to reduce API calls for same-day reruns [PRIORITY: MED]
- [ ] Ingest analyst estimate revisions as a scheduled data feed [PRIORITY: LOW]

## Infrastructure
- [ ] Alembic migrations setup with auto-generate [PRIORITY: HIGH]
- [ ] Prometheus metrics endpoint for agent run durations and failure rates [PRIORITY: MED]
- [ ] Health check endpoint that validates DB + OpenViking connectivity [PRIORITY: HIGH]
- [ ] Add Redis for task queue (Celery or ARQ) if APScheduler proves insufficient [PRIORITY: LOW]
