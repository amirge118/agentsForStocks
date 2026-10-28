# Future Improvements

Add ideas and "nice to haves" discovered during implementation here.
Format: `- [ ] Description [PRIORITY: HIGH / MED / LOW]`

**Current focus: reliability and improving what exists, not new features.** Sections 1–4 are
in order of work; within a section, top first. New capabilities wait in section 6 until the
current pipeline is trustworthy and measured. A new idea goes in the section it belongs to.

## 1. Reliability now — the pipeline must not lie or break silently
- [ ] Protect `main` in GitHub settings: require the CI checks to pass before merging, no direct pushes (a setting, not code) [PRIORITY: HIGH]
- [x] No silent HOLD: a result built on a fallback (model unavailable or its reply unreadable) carries `needs_review` with the reason, and so does a recommendation that held for lack of analysts or built on an analyst that fell back; shown on the verdict, the breakdown, the panels and the watchlist
- [x] Audit for "missing field = 0": risk (D/E, current ratio, beta, short ratio), institutional (ownership, flows → `unknown`), broad_analysis (market cap) now say N/A; EV/EBITDA needs reported debt; owner earnings assume maintenance ≈ D&A when capex is missing; the liquidity trend and yearly growth skip a missing figure
- [x] Tests read the real environment: five tests (`test_llm_router.py`, `test_preflight.py`, `test_api.py::test_agents_show_their_effective_profile`) fail when `GEMINI_API_KEY` / `GROQ_API_KEY` / `LLM_PROVIDER` are set in the shell — isolated: conftest drops every Settings variable from the environment and ignores `.env`
- [x] CI: `timeout-minutes` on the Playwright install (it hung twice before any test ran) and the browser cached per Playwright version
- [ ] Persist the FMP call counter in the DB: a restart resets the in-process `DailyCallBudget`, so a day with a restart can pass the 250 free calls [PRIORITY: MED]
- [ ] Alert when a scheduled run is missed or fails (the worker is up but the job never finished) [PRIORITY: MED]
- [ ] Per-day LLM cost budget (like the FMP DailyCallBudget) that stops new calls and alerts when exceeded — needed before the chain can reach Claude unattended [PRIORITY: MED]
- [ ] Agent retry: when yfinance or FMP is down, retry the failed (agent, symbol) later in the day instead of leaving the day empty [PRIORITY: MED]
- [ ] Check that a ticker exists (a quote) when it is added to the watchlist, not only its format [PRIORITY: MED]
- [ ] Postgres advisory lock around the daily job, so even two workers can never both run it [PRIORITY: LOW]
- [ ] Persist the manual-run lock in the DB, so it also holds across several backend workers [PRIORITY: LOW]

## 2. Go live and verify on real data
- [ ] Go live: a hosted Postgres (`DATABASE_URL`), the keys (`FMP_API_KEY`, the free-chain `*_API_KEY`s, `ANTHROPIC_API_KEY`, `API_KEYS`, `DASHBOARD_PASSWORD`), one `python -m app.worker` with `SCHEDULER_ENABLED=true` and `RUN_SCHEDULER=false` on the API; confirm with `python -m scripts.preflight` and the first scheduled `daily_pipeline` [PRIORITY: HIGH]
- [ ] First run with `ANTHROPIC_API_KEY`: preflight confirms a live request on SDK 2.x / API version 2026-10-21, and one `run_pipeline` exercises the chain's last step (Claude Haiku 5.5) and the reasoning model [PRIORITY: HIGH]
- [ ] Smoke-test yfinance against live Yahoo from production (yfinance 1.x fetches through curl_cffi; Yahoo isn't reachable from CI / the dev sandbox) [PRIORITY: MED]
- [ ] Publish images to GHCR and add a deploy workflow [PRIORITY: MED]

## 3. Data quality — close the gaps the agents run with today
- [ ] The cloud environment's proxy refuses yfinance's news, insider-trade and earnings-date calls (HTTP 403 on the CONNECT): sentiment ran with no headlines and earnings without dates. Check whether production reaches them; if not, take news and insider trades from FMP (`/stable/news/stock`, `/stable/insider-trading`) [PRIORITY: HIGH]
- [ ] FMP free plan: institutional ownership and earnings-call transcripts return 402, so `institutional` and `growth` always answer neutral 0% (weights 5 and 10 contribute nothing). Either a free source (SEC 13F for holders, 8-K exhibits for transcripts) or lower their weights until one exists — confirm with backtest A [PRIORITY: MED]
- [ ] FMP budget: ~22 calls per symbol per run (~110/250 for 5 symbols). Share one statements fetch per symbol across agents (they ask for different `limit`s, so the cache misses), or cache annual statements for a day [PRIORITY: MED]
- [ ] More invariants: risk (bullish with D/E > 3 and current ratio < 1), earnings (beat rate ≥ 75% + positive reaction yet bearish), institutional (distributing yet bullish) — normalise D/E units first (FMP ratio vs Yahoo percent) [PRIORITY: MED]
- [x] Show data gaps, contract violations and `needs_review` per agent on the symbol page, so a weak result is visible as weak
- [ ] FMP earnings history: the free plan caps `earnings?limit` at 5, so the earnings agent sees half its 8-quarter window — make the limit a setting (`FMP_EARNINGS_LIMIT`) for paid plans [PRIORITY: LOW]
- [ ] Re-review results stored before the per-agent compliance gate existed (they have no `compliance` field) [PRIORITY: LOW]

## 4. Measure, then improve what exists (needs settled outcomes)
Change a prompt, model, weight or skill only on evidence: an eval report or an out-of-sample backtest win.
- [ ] Run the outcome eval suite live once a few weeks of recommendations have settled — the baseline for every later prompt / model change [PRIORITY: HIGH]
- [ ] Run backtest A once a few weeks have settled; change weights only on a clear out-of-sample win. Includes the weight-0 agents (fundamentals / technicals / sentiment / market_scanner) [PRIORITY: HIGH]
- [ ] One live model baseline (needs `ANTHROPIC_API_KEY`): the free chain and free_gemini presets vs claude-haiku-5-5 / claude-sonnet-5-5, `--repeats 3 --judge`; then decide the default provider and models [PRIORITY: HIGH]
- [ ] Decide on the ready experiments with that eval, and make the winners defaults: prompts_v2, haiku55, rule_based_quant (−2 calls per symbol), skills per agent, cheap_alt_news [PRIORITY: MED]
- [ ] Valuation calibration: re-check against settled outcomes (the live pin is AAPL vs MSFT, 2026-10-26); tie growth to reinvestment (g ≈ ROIC × reinvestment rate) so growth capex isn't both excluded from cash flow and credited with the growth [PRIORITY: MED]
- [ ] Historical market cap for point-in-time runs: close on `as_of` × shares outstanding from the last filed statement, so valuation / fundamentals / market_scanner work in historical runs instead of answering 0% on the withheld `info` [PRIORITY: MED]
- [ ] Backtest B: re-run the pipeline over a grid of past dates into a separate database, settle it, then the same reports as A — `docs/plans/backtest.md`. After the historical market cap [PRIORITY: MED]
- [ ] Type-check the backend with mypy in CI (strict for `app/llm`) — the provider Protocol is only checked by tests today [PRIORITY: MED]
- [ ] Backtest A on more than one agent at a time (pairs, or a coordinate search) once there are enough cases that it won't just fit noise [PRIORITY: LOW]
- [ ] Track record over time: hit rate per month per agent on `/track-record`, to see whether a change helped — needs a few months of settled calls [PRIORITY: LOW]

## 5. Operations hygiene
- [ ] Grafana alerts: failed runs, fallbacks, daily LLM cost above a threshold, FMP budget at 80%, a free tier past 90% of its daily limit [PRIORITY: MED]
- [ ] Give Grafana a read-only Postgres role instead of the app's credentials [PRIORITY: LOW]
- [ ] Send the observability data to a hosted backend (Grafana Cloud / Honeycomb) for a deployed instance — only OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS change [PRIORITY: LOW]
- [ ] Make uvicorn's own access/startup logs use the JSON formatter too (`--log-config`) [PRIORITY: LOW]
- [ ] Pin GitHub Actions by commit SHA and Docker base images by digest (Dependabot keeps them updated) [PRIORITY: LOW]
- [ ] Re-read the free-tier limits each quarter: they change often (Gemini cut Pro to ~50/day, Groq dropped Llama from its free tier) [PRIORITY: LOW]
- [ ] Move the provider cache, the FMP counter and the free-tier quota state to Redis — only once there is more than one process [PRIORITY: LOW]
- [ ] Add OpenViking connectivity to /health (only when OPENVIKING_ENABLED) [PRIORITY: LOW]
- [ ] Re-sync the hand-written shadcn primitives in `src/components/ui` with `npx shadcn add` when the CLI is reachable [PRIORITY: LOW]

### Dependencies to watch
- [ ] yfinance (1.7.0) calls `DataFrame.rename(..., inplace=True)`, which pandas 3.1 deprecates — check before a pandas 4 upgrade [PRIORITY: LOW]
- [ ] yfinance 1.x `earnings_dates` gives `Surprise(%)` in percent (4.52), 0.2.50 gave a fraction — nothing reads it today; scale it if an agent starts using it [PRIORITY: LOW]
- [ ] TypeScript 7 (native Go compiler): typescript-eslint (`<6.1`) and Next's build type-check need the classic compiler API — upgrade once both support TS 7, and drop its `ignore` in `.github/dependabot.yml` [PRIORITY: LOW]
- [ ] openapi-typescript 7.13 declares `typescript ^5`; an npm `overrides` entry gives it TS 6 (output verified identical) — drop the override when it supports TS 6 [PRIORITY: LOW]
- [ ] ESLint 10: eslint-plugin-react / -import / -jsx-a11y (inside eslint-config-next 16) still declare `eslint ≤9` peers, so `npm ci` prints ERESOLVE warnings; their rules were checked to fire under 10 [PRIORITY: LOW]
- [ ] Unpin aiosqlite (held at 0.20.0, test-only): with SQLAlchemy 2.1.6, 0.22.1 hangs the event loop at teardown after a session is cancelled mid-query. Retry when either library fixes it — check with `pytest tests/integration/test_api.py`, and drop its `ignore` in `.github/dependabot.yml` [PRIORITY: LOW]
- [ ] Dependabot `cooldown` (≥7 days before a new release gets a PR), then consider auto-merging patch updates of dev dependencies once CI is green [PRIORITY: LOW]

## 6. Parked — new capabilities (not now)
Revisit once sections 1–4 are done. Priorities are relative within this section.

### Agents
- [ ] PortfolioHealthAgent — portfolio-level risk scoring and rebalancing signals [PRIORITY: MED]
- [ ] PortfolioManagerAgent — aggregates all agent signals → buy/sell/hold decisions (adapted from ai-hedge-fund portfolio_manager.py) [PRIORITY: MED]
- [ ] Bull/bear debate as a `recommendation` prompt variant — plan in `docs/plans/bull-bear-debate.md`; ship only if the scenario and outcome evals beat the current prompt, it triples the recommendation's calls [PRIORITY: MED]
- [ ] Macro regime input for risk / recommendation from FRED (fed funds, 2y/10y, curve, CPI, unemployment, VIX), via a FRED provider (`app/providers/fred.py`, free key, vintage-aware) [PRIORITY: MED]
- [ ] SectorTrendAgent — sector rotation detection using ETF relative strength (see skills/sector_rotation.md) [PRIORITY: LOW]
- [ ] CompsAgent — comparable company analysis (see skills/comparable_companies.md) [PRIORITY: LOW]
- [ ] Fund-specific agents: holdings concentration, expense ratio, tracking error, flows — then a fund recommendation [PRIORITY: LOW]
- [ ] Personality agents (Warren Buffett, Charlie Munger style) using ai-hedge-fund patterns [PRIORITY: LOW]
- [ ] Hit rate per analyst agent in its own prompt ("your bullish calls on this symbol were right 3/7 times") — measure with the outcome suite first [PRIORITY: LOW]
- [ ] Valuation: analyst forward estimates next to the revenue history; risk-free rate from the 10-year Treasury instead of a constant [PRIORITY: LOW]

### Data
- [ ] Alpha Vantage as a fallback source when yfinance is unavailable [PRIORITY: MED]
- [ ] Sector-ETF benchmark (XLK, XLV, ...) as a second alpha in `decision_outcomes`, to separate stock picking from sector beta [PRIORITY: LOW]
- [ ] Per-market benchmark for alpha by ticker suffix (SPY, `.TA` → TA-35, `.L` → FTSE, ...) [PRIORITY: LOW]
- [ ] EDGAR: parse iXBRL/HTML structure instead of regex for unusual 10-K layouts [PRIORITY: LOW]
- [ ] Analyst estimate revisions as a scheduled data feed [PRIORITY: LOW]
- [ ] StockTwits / Reddit posts for the sentiment agent, screened by a cheap model [PRIORITY: LOW]
- [ ] Polymarket implied probabilities (Fed decision, recession) as macro context [PRIORITY: LOW]

### Knowledge layer (OpenViking)
- [ ] Enable OpenViking: copy ov.conf.example → ov.conf, add ANTHROPIC_API_KEY, run `docker compose up openviking openviking-mcp`, then `python infra/openviking/seed.py`. Set OPENVIKING_ENABLED=true in .env [PRIORITY: LOW]
- [ ] Point-in-time knowledge recall: store each learning with its run date and recall only older ones, instead of skipping the knowledge base on historical runs [PRIORITY: LOW]
- [ ] Auto-detect and store "anomaly" patterns when a result deviates >2σ from history [PRIORITY: LOW]
- [ ] Knowledge quality scoring — which recalled patterns improved accuracy [PRIORITY: LOW]
- [ ] Dashboard to browse the knowledge base; periodic pruning of cases older than 2 years [PRIORITY: LOW]

### MCP data sources (Claude for Financial Advisors plugin)
- [ ] Wire `mcp_servers` into FundamentalsAgent with one licensed provider (Daloopa or S&P Global/Kensho); token via settings/env [PRIORITY: MED]
- [ ] Persist the MCP tool calls Claude made (server, tool, input) on the agent result — required before any MCP source goes live [PRIORITY: MED]
- [ ] Per-provider rate limiting / call budget for MCP tools (Claude decides when to call them, bypassing app/providers) [PRIORITY: MED]
- [ ] Morningstar MCP (fair value, moat rating) as a cross-check in MoatAgent / ValuationAgent [PRIORITY: LOW]

### LLM
- [ ] Message Batches API (−50%) for the scheduled daily run, one batch per dependency level — once the daily cost is meaningful [PRIORITY: LOW]
- [ ] Prompt caching — only pays once a system prompt (+ skills) exceeds the model's minimum cacheable prefix; today's prompts are 60–250 tokens [PRIORITY: LOW]
- [ ] Skills with data hooks (e.g. comparable_companies fetching peers) instead of text-only guidance [PRIORITY: LOW]
- [ ] More chain steps: OpenRouter `:free` models, Mistral's free tier (trains on inputs), a local Ollama [PRIORITY: LOW]
- [ ] Load model prices from config instead of `app/llm/pricing.py` [PRIORITY: LOW]
- [ ] Optional weekly eval in GitHub Actions with a key secret, posting the report as an artifact [PRIORITY: LOW]
- [ ] Optional LLM second-pass compliance review for subtler issues (cherry-picking, unbalanced framing) [PRIORITY: LOW]

### API & frontend
- [ ] Real login (OIDC / NextAuth) instead of Basic auth once there is more than one user [PRIORITY: MED]
- [ ] Scoped API keys (read-only vs. can trigger runs) and per-key rate limiting [PRIORITY: LOW]
- [ ] Endpoint / report listing recommendations that were flagged or failed compliance [PRIORITY: LOW]
- [ ] Show the scheduled jobs and their next runs on the dashboard (`GET /api/v1/schedules`) [PRIORITY: LOW]
- [ ] Agents page from GET /api/v1/agents (dependency graph + weights) [PRIORITY: LOW]
- [ ] Expose the BUY / SELL thresholds through the API instead of mirroring them in `frontend/src/lib/scoring.ts` [PRIORITY: LOW]
- [ ] Panels for the remaining agents' own metrics (moat, institutional, financial history, market scanner) [PRIORITY: LOW]
- [ ] Cursor pagination for /runs and /symbols/{symbol}/results [PRIORITY: LOW]
- [ ] Watchlist groups / tags and per-group runs [PRIORITY: LOW]
- [ ] Story: name the analysts not weighted in the score in the opening [PRIORITY: LOW]
- [ ] Price chart: weekly bars over 1Y, intraday for 1D/5D [PRIORITY: LOW]
- [ ] Light mode: Console's "paper" colourway behind `prefers-color-scheme` [PRIORITY: LOW]
- [ ] Mobile: stack the `/track-record` calibration table per agent (scrolls sideways at 390px); popover instead of tooltip for the compliance marker on touch [PRIORITY: LOW]
- [ ] Move the watchlist and recommendation card onto the shared query states [PRIORITY: LOW]
- [ ] Run Hallmark's rendered sloplint (`--render --url`) in CI (needs puppeteer-core + Chrome) [PRIORITY: LOW]
- [ ] Redis task queue (Celery or ARQ) if APScheduler proves insufficient [PRIORITY: LOW]

## Done
- [x] Alembic migrations; Dockerfiles (API / worker / migrations / Next standalone), full Compose stack + CI smoke test
- [x] CI (GitHub Actions): lint, format, bandit, pip-audit / npm audit, pytest on SQLite + PostgreSQL, migration check, Jest, Playwright; Dependabot weekly
- [x] OpenTelemetry traces, metrics and logs; `observability` compose profile with Grafana + dashboard; structured JSON logging with secret scrubbing
- [x] `/health` with DB connectivity + scheduler state; scheduler in a dedicated worker; scheduled jobs off by default (`SCHEDULER_ENABLED`), one jobs table
- [x] Preflight and manual run CLI; first real pipeline runs (AAPL, MSFT, free chain, $0) — the latest 2026-10-27: 14/14 agents, 0 fallbacks, BUY 70%
- [x] Authentication: X-API-Key (fail-closed in production), dashboard Basic auth, server-side key proxy with CSRF checks; one manual run at a time (409)
- [x] Providers: TTL cache, FMP daily budget, FMP `/stable/`, Yahoo chart fallback (history, quote, adjusted closes for settlement), FMP fill of `info` fundamentals, EDGAR entity decoding
- [x] Funds (ETFs) run only the market agents (`company_only=True`, `isEtf` / `quoteType`)
- [x] Agent contracts: data gaps, no-data confidence cap, invariants, prompt snapshots, golden scenarios; risk cap enforced in code (non-bearish → HOLD ≤55%)
- [x] Compliance review on every agent's reasoning, markers and tooltips in the frontend
- [x] Valuation from the company's own numbers: revenue-history growth, CAPM discount rate, owner earnings, no double haircut, reverse DCF
- [x] Outcome settlement (phases 1–4): `decision_outcomes`, the outcome_review lessons, track record API / page / card, outcome evals
- [x] Backtest A (`scripts.backtest_weights`) and the point-in-time guard for historical runs (`run_pipeline --date`)
- [x] LLM: profiles, skills, OpenAI-compatible providers, free-tier chain with quotas, provider visibility, the `llm_calls` ledger, eval harness, 10-K excerpts (−31% input tokens), `anthropic` SDK 2.3.0
- [x] Frontend: Next.js 16 dashboard with OpenAPI-checked Zod types, watchlist management (drag-to-reorder, mobile menu), symbol detail, analysis story, Hallmark "Console" design system
- [x] Dependencies: split requirements, fastapi 0.162 / starlette 1.10, yfinance 1.7, SQLAlchemy 2.1.6, pandas 3.1, Jest 30, Tailwind 4, TypeScript 6, ESLint 10
