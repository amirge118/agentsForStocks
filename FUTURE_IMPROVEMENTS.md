# Future Improvements

Add ideas and "nice to haves" discovered during implementation here.
Format: `- [ ] Description [PRIORITY: HIGH / MED / LOW]`

## Agents
- [x] BroadAnalysisAgent, FinancialHistoryAgent, MoatAgent, RiskAgent, GrowthAgent, InstitutionalAgent, EarningsAgent, RecommendationAgent — all implemented
- [ ] Add PortfolioHealthAgent — portfolio-level risk scoring and rebalancing signals [PRIORITY: HIGH]
- [ ] Add SectorTrendAgent — sector rotation detection using ETF relative strength (see skills/sector_rotation.md) [PRIORITY: MED]
- [ ] Add PortfolioManagerAgent — aggregates all agent signals → buy/sell/hold decisions (adapted from ai-hedge-fund portfolio_manager.py) [PRIORITY: HIGH]
- [ ] Add personality agents (Warren Buffett, Charlie Munger style) using ai-hedge-fund patterns [PRIORITY: LOW]
- [ ] Add CompsAgent — comparable company analysis (see skills/comparable_companies.md) [PRIORITY: MED]
- [ ] Agent retry queue — if yfinance or FMP is down, queue the run for 30min later [PRIORITY: MED]
- [ ] Decide recommendation weights for fundamentals / technicals / sentiment / market_scanner (currently weight 0 = informational only; set via @register_agent) [PRIORITY: MED]
- [ ] Backtest the recommendation weights and BUY/SELL thresholds against historical prices [PRIORITY: HIGH]

## Knowledge Layer (OpenViking)
- [ ] Enable OpenViking: copy ov.conf.example → ov.conf, add ANTHROPIC_API_KEY, run `docker compose up openviking openviking-mcp`, then `python infra/openviking/seed.py`. Set OPENVIKING_ENABLED=true in .env [PRIORITY: LOW]

- [ ] Auto-detect and store "anomaly" patterns when analysis result deviates >2σ from historical [PRIORITY: MED]
- [ ] Dashboard to browse knowledge base (list patterns/cases per symbol) [PRIORITY: LOW]
- [ ] Knowledge quality scoring — track which recalled patterns improved analysis accuracy [PRIORITY: LOW]
- [ ] Periodic knowledge pruning — archive cases older than 2 years [PRIORITY: LOW]

## Data
- [ ] Add Alpha Vantage as fallback data source when yfinance is unavailable [PRIORITY: MED]
- [x] Cache yfinance + FMP responses for same-day reruns (in-process TTL cache in app/providers/cache.py)
- [ ] Move the provider cache to Redis so it is shared across processes/restarts [PRIORITY: MED]
- [x] FMP daily call budget with warning at 80% (app/providers/fmp.py DailyCallBudget, in-process)
- [ ] Persist the FMP call counter in Redis/DB so restarts don't reset it [PRIORITY: MED]
- [ ] Reduce FMP calls during dev: use only 5 symbols in DEFAULT_SYMBOLS until Redis caching is in place [PRIORITY: MED]
- [x] EDGAR extraction: HTML entity decoding + skip table-of-contents matches
- [ ] EDGAR: parse iXBRL/HTML structure instead of regex for unusual 10-K layouts [PRIORITY: LOW]
- [ ] Ingest analyst estimate revisions as a scheduled data feed [PRIORITY: LOW]

## Infrastructure
- [x] Alembic migrations setup with auto-generate (backend/alembic, `alembic upgrade head`)
- [ ] Prometheus metrics endpoint for agent run durations and failure rates [PRIORITY: MED]
- [x] Health check endpoint validating DB connectivity + scheduler state (`/health`, 503 when degraded)
- [ ] Add OpenViking connectivity to /health (only when OPENVIKING_ENABLED) [PRIORITY: LOW]
- [ ] Add Redis for task queue (Celery or ARQ) if APScheduler proves insufficient [PRIORITY: LOW]
- [ ] Run the scheduler in a single dedicated worker process — with several uvicorn workers each would start its own scheduler [PRIORITY: HIGH]
- [ ] Add CI (GitHub Actions): ruff, black --check, bandit, pytest with coverage gate [PRIORITY: HIGH]
- [ ] Structured JSON logging so `extra=` fields (symbol, run_id) reach the log output [PRIORITY: MED]

## API & Frontend
- [ ] REST endpoints under /api/v1: symbols, latest recommendation, agent results, agent_runs, manual pipeline trigger [PRIORITY: HIGH]
- [ ] Next.js frontend per CLAUDE.md; generate TS types from FastAPI OpenAPI (openapi-typescript) + Zod at the boundary [PRIORITY: HIGH]

## LLM
- [ ] Upgrade the `anthropic` SDK pin (0.40) so structured outputs use the typed `output_config` parameter instead of `extra_body` [PRIORITY: MED]
- [ ] Evaluate newer models (claude-haiku-5-5 / claude-sonnet-5-5) for agent judgements via LLM_DEFAULT_MODEL / LLM_REASONING_MODEL — needs an eval set first [PRIORITY: MED]
