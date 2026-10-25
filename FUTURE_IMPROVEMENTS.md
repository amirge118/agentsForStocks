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
- [x] Scheduler in a dedicated worker process (`python -m app.worker`, RUN_SCHEDULER=false on the API)
- [ ] Postgres advisory lock around the daily job so even two workers can never both run it [PRIORITY: LOW]
- [x] Preflight (`python -m scripts.preflight`) and manual run CLI (`python -m scripts.run_pipeline`)
- [ ] First real pipeline run against live Claude / FMP / Yahoo / SEC — blocked in the cloud environment until its network policy allows those hosts and the API keys are configured [PRIORITY: HIGH]
- [x] CI (GitHub Actions): lint, format, bandit, pip-audit / npm audit, pytest on SQLite + PostgreSQL, migration check, Jest, Playwright
- [ ] Protect `main` in GitHub settings: require the CI checks to pass before merging, no direct pushes [PRIORITY: HIGH]
- [ ] Dependabot (pip, npm, github-actions) so pinned versions get security updates [PRIORITY: MED]
- [ ] Pin GitHub Actions by commit SHA instead of major tag [PRIORITY: LOW]
- [ ] Backend Dockerfile + deploy workflow (migrations on release) [PRIORITY: MED]
- [ ] Structured JSON logging so `extra=` fields (symbol, run_id) reach the log output [PRIORITY: MED]

## API & Frontend
- [x] REST endpoints under /api/v1: agents, symbols overview, latest recommendation, agent results, agent_runs, manual pipeline trigger (202, background)
- [x] Authentication on /api/v1 (X-API-Key, fail-closed in production) + dashboard Basic auth + server-side key proxy with CSRF checks
- [ ] Replace dashboard Basic auth with real login (OIDC / NextAuth) once there is more than one user [PRIORITY: MED]
- [ ] Scoped API keys (read-only vs. can trigger runs) and per-key rate limiting [PRIORITY: LOW]
- [x] One manual pipeline run at a time (409 while a run is active)
- [ ] Persist the 'run active' lock in the DB so it also holds across several backend workers [PRIORITY: LOW]
- [ ] Cursor pagination for /runs and /symbols/{symbol}/results instead of limit-only [PRIORITY: LOW]
- [ ] Manage the watchlist through the API (DB table) instead of the WATCHLIST env var [PRIORITY: MED]
- [x] Next.js frontend: watchlist, symbol detail, run history; types generated from OpenAPI + Zod validated and checked against them
- [ ] Symbol detail: per-agent result panels (valuation DCF scenarios, technical strategies, moat keywords) from /symbols/{symbol}/results [PRIORITY: MED]
- [ ] Charts: recommendation score history and price history per symbol [PRIORITY: MED]
- [ ] Agents page from GET /api/v1/agents (dependency graph + weights) [PRIORITY: LOW]
- [ ] shadcn CLI was unreachable from the build environment — primitives in src/components/ui were written from the shadcn source; re-sync with `npx shadcn add` when online [PRIORITY: LOW]
- [ ] Move to Next.js 16 when CLAUDE.md allows — Next 15 bundles a vulnerable postcss, currently forced to 8.5.31 via npm overrides [PRIORITY: MED]

## LLM
- [ ] Upgrade the `anthropic` SDK pin (0.40) so structured outputs use the typed `output_config` parameter instead of `extra_body` [PRIORITY: MED]
- [ ] Evaluate newer models (claude-haiku-5-5 / claude-sonnet-5-5) for agent judgements via LLM_DEFAULT_MODEL / LLM_REASONING_MODEL — needs an eval set first [PRIORITY: MED]

## MCP Data Sources (Claude for Financial Advisors plugin)
- [x] MCP connector support in LLMClient / Agent.judge(mcp_servers=...) (app/llm/mcp.py)
- [ ] Wire `mcp_servers` into FundamentalsAgent with one licensed provider (Daloopa or S&P Global/Kensho); token via settings/env [PRIORITY: HIGH]
- [ ] Persist the MCP tool calls Claude made (server, tool, input) on the agent result so runs stay auditable and reproducible [PRIORITY: HIGH]
- [ ] Per-provider rate limiting / call budget for MCP tools (Claude decides when to call them, bypassing app/providers) [PRIORITY: MED]
- [ ] Use Morningstar MCP (fair value, moat rating) as a cross-check in MoatAgent / ValuationAgent [PRIORITY: MED]
- [x] Compliance pass on RecommendationAgent output (app/domain/compliance.py): promissory language fails and is replaced, hype / missing-risk is flagged, disclaimer on every result; shown in the frontend
- [ ] Run the compliance review on every agent's `reasoning`, not just RecommendationAgent (all are user-visible) [PRIORITY: MED]
- [ ] Optional LLM second-pass compliance review for subtler issues (cherry-picking, unbalanced framing) the regex rules miss [PRIORITY: LOW]
- [ ] Endpoint / report listing recommendations that were flagged or failed compliance, for review [PRIORITY: LOW]

## Dependencies
- [x] Split requirements: runtime / dev / optional knowledge (OpenViking pulls ~300 packages)
- [x] fastapi 0.115 → 0.162 with starlette 1.10 (0.38.x had 14 known vulnerabilities); removed unused python-jose + bcrypt
- [ ] Upgrade the remaining old pins (anthropic 0.40, yfinance 0.2.50, pandas 2.2, SQLAlchemy 2.0.36) one at a time with the test suite [PRIORITY: MED]
