# Future Improvements

Add ideas and "nice to haves" discovered during implementation here.
Format: `- [ ] Description [PRIORITY: HIGH / MED / LOW]`

## Agents
- [x] Valuation from the company's own numbers: revenue-history growth, CAPM discount rate, owner earnings (maintenance capex ≈ D&A), no double haircut, reverse DCF (implied growth)
- [ ] Valuation: tie growth to reinvestment (g ≈ ROIC × reinvestment rate) so growth capex isn't both excluded from cash flow and credited with the growth [PRIORITY: MED]
- [ ] Valuation: analyst forward estimates (FMP `analyst-estimates`, if in the plan) next to the revenue history; risk-free rate from the 10-year Treasury instead of a constant [PRIORITY: LOW]
- [x] Funds (ETFs) run only the market agents; company-only agents are skipped (`company_only=True`)
- [ ] Fund-specific agents: holdings concentration, expense ratio, tracking error, flows — then a fund recommendation [PRIORITY: LOW]
- [x] Agent contracts: data gaps, no-data confidence cap, invariants (valuation, fundamentals, technicals), risk cap enforced in code; golden scenarios; prompt snapshots with a size budget
- [ ] More invariants: risk (bullish with D/E > 3 and current ratio < 1), earnings (beat rate ≥ 75% + positive reaction yet bearish), institutional (distributing yet bullish) — normalise D/E units first (FMP ratio vs Yahoo percent) [PRIORITY: MED]
- [ ] Show data gaps and contract violations per agent on the symbol page [PRIORITY: MED]
- [x] BroadAnalysisAgent, FinancialHistoryAgent, MoatAgent, RiskAgent, GrowthAgent, InstitutionalAgent, EarningsAgent, RecommendationAgent — all implemented
- [ ] Add PortfolioHealthAgent — portfolio-level risk scoring and rebalancing signals [PRIORITY: HIGH]
- [ ] Add SectorTrendAgent — sector rotation detection using ETF relative strength (see skills/sector_rotation.md) [PRIORITY: MED]
- [ ] Add PortfolioManagerAgent — aggregates all agent signals → buy/sell/hold decisions (adapted from ai-hedge-fund portfolio_manager.py) [PRIORITY: HIGH]
- [ ] Add personality agents (Warren Buffett, Charlie Munger style) using ai-hedge-fund patterns [PRIORITY: LOW]
- [ ] Add CompsAgent — comparable company analysis (see skills/comparable_companies.md) [PRIORITY: MED]
- [ ] Agent retry queue — if yfinance or FMP is down, queue the run for 30min later [PRIORITY: MED]
- [ ] Decide recommendation weights for fundamentals / technicals / sentiment / market_scanner (currently weight 0 = informational only; set via @register_agent) [PRIORITY: MED]
- [x] Backtest the recommendation weights and BUY/SELL thresholds against historical prices — backtest A (`scripts.backtest_weights`); running it waits for settled data (see below)
- [x] Outcome settlement, phase 1: `decision_outcomes` table, nightly settlement before the daily pipeline (backfills history), `scripts.settle_outcomes`
- [x] Outcome settlement, phase 3: `outcome_review` agent writes a lesson per settled recommendation; the recommendation prompt gets a point-in-time track record (hit rate, alpha captured, lessons)
- [x] Outcome settlement, phase 4: `evals.capture --outcomes` + `evals.run --suite outcomes` — replays captured prompts and grades a configuration by hit rate and alpha captured against what really followed
- [x] Outcome settlement, phase 2: `GET /api/v1/outcomes/track-record` (per agent: hit rate, alpha captured, per signal and confidence bucket) and `/symbols/{symbol}/outcomes`, `scripts.track_report`, the `/track-record` page and a "Track record" card on the symbol page
- [ ] Track record over time: hit rate per month per agent (a chart on `/track-record`) to see whether a prompt or model change helped — needs a few months of settled calls [PRIORITY: LOW]
- [ ] Mobile: the calibration table on `/track-record` scrolls sideways at 390px; consider stacking it per agent [PRIORITY: LOW]
- [x] Yahoo chart fallback for `YFinanceClient.get_closes` (settlement): `YahooChartClient.get_adjusted_closes` reads the chart's `adjclose` for an exact date range (period1/period2) — never unadjusted closes; verified live equal to yfinance's auto-adjusted closes
- [x] Risk override caps the confidence too: any non-bearish call under the override is HOLD at ≤55% (`scoring.risk_capped`), also when the model answers HOLD itself; the `risk_override/recommendation` eval case went from 20% to 100% within its limit (Gemini, 10 repeats)
- [ ] Run the outcome eval suite live once a few weeks of recommendations have settled (current prompt as the baseline for every later prompt/model change) [PRIORITY: HIGH]
- [ ] Hit rate per analyst agent in its own prompt ("your bullish calls on this symbol were right 3/7 times") — easy with phase 2's query; measure with the outcome suite first [PRIORITY: LOW]
- [x] Backtest A: `python -m scripts.backtest_weights` replays the stored analyst calls with 136 weight/threshold configurations (current, equal, each agent dropped / x0.5 / x1.5 / x2, thresholds ±10–25) against the settled outcomes; fit on the first 70% of days, reported on the rest, next to the stored LLM recommendations
- [ ] Run backtest A once a few weeks have settled, and change weights only on a clear out-of-sample win [PRIORITY: HIGH]
- [ ] Backtest B: re-run the pipeline over a grid of past dates (the point-in-time guard is in) into a separate database, settle it, then the same reports as A — `docs/plans/backtest.md` [PRIORITY: MED]
- [ ] Backtest A on more than one agent at a time (pairs, or a coordinate search) once there are enough cases that it won't just fit noise [PRIORITY: LOW]
- [x] Point-in-time guard for historical runs (`app/providers/point_in_time.py`): a past run date gets providers that keep dated history up to it (prices, statements by filing date, the 10-K filed by then, earnings before it, insider trades and news on or before it), keep period data once reported (ratios and key metrics 90 days after the period, 13F 45 days), and withhold live snapshots (`info`, the profile's market fields, current holders, estimates) as data gaps; the knowledge base is not consulted. `python -m scripts.run_pipeline AAPL --date 2026-06-15` — checked live: 14/14 agents, statements as filed by then
- [ ] Historical market cap for point-in-time runs: close on `as_of` × shares outstanding from the last filed statement, so valuation / fundamentals / market_scanner work in backtests instead of answering 0% on the withheld `info` [PRIORITY: MED]
- [ ] Point-in-time knowledge recall: store each learning with its run date and recall only older ones, instead of skipping the knowledge base on historical runs [PRIORITY: LOW]
- [ ] Bull/bear debate as a `recommendation` prompt variant (one bull and one bear pass, then the decision; "conflict alone is not a reason to HOLD") — plan in `docs/plans/bull-bear-debate.md`; ship only if the scenario and outcome evals beat the current prompt, it triples the recommendation's calls (TradingAgents `agents/researchers/`) [PRIORITY: MED]
- [ ] Check that no parse/LLM failure is silently stored as a neutral HOLD; mark it as needing review instead (TradingAgents `rating.py` `REVIEW`) [PRIORITY: MED]
- [ ] Macro regime input for risk / recommendation from FRED (fed funds, 2y/10y, curve, CPI, unemployment, VIX; free key) [PRIORITY: MED]

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
- [ ] FRED provider (`app/providers/fred.py`, free key, curated alias → series map, vintage-aware) — feeds the macro regime item under Agents [PRIORITY: MED]
- [ ] StockTwits / Reddit posts for the sentiment agent, screened by a cheap model (drop off-topic posts, count bullish / bearish) before they reach the prompt [PRIORITY: LOW]
- [ ] Polymarket implied probabilities (Fed decision, recession) as macro context; public API, no key [PRIORITY: LOW]
- [ ] Sector-ETF benchmark (XLK, XLV, ...) as a second alpha in `decision_outcomes`, to separate stock picking from sector beta [PRIORITY: LOW]
- [ ] Per-market benchmark for alpha by ticker suffix (SPY, `.TA` → TA-35, `.L` → FTSE, ...) [PRIORITY: LOW]

## Infrastructure
- [x] Alembic migrations setup with auto-generate (backend/alembic, `alembic upgrade head`)
- [x] OpenTelemetry: traces (pipeline → symbol → agent → fetch/analyze → HTTP/SQL/yfinance/Claude), metrics, logs over OTLP; `observability` compose profile with Grafana + dashboard
- [ ] Grafana alerts: failed runs, fallbacks, daily LLM cost above a threshold, FMP budget at 80% [PRIORITY: MED]
- [ ] Give Grafana a read-only Postgres role instead of the app's credentials [PRIORITY: LOW]
- [ ] Send the observability data to a hosted backend (Grafana Cloud / Honeycomb) for a deployed instance — only OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS change [PRIORITY: LOW]
- [x] Health check endpoint validating DB connectivity + scheduler state (`/health`, 503 when degraded)
- [ ] Add OpenViking connectivity to /health (only when OPENVIKING_ENABLED) [PRIORITY: LOW]
- [ ] Add Redis for task queue (Celery or ARQ) if APScheduler proves insufficient [PRIORITY: LOW]
- [x] Scheduler in a dedicated worker process (`python -m app.worker`, RUN_SCHEDULER=false on the API)
- [x] Scheduled jobs off by default (`SCHEDULER_ENABLED`), one jobs table with a crontab setting per job, `python -m scripts.schedules` lists them
- [ ] Show the scheduled jobs and their next runs on the dashboard (`GET /api/v1/schedules`) [PRIORITY: LOW]
- [ ] Alert when a scheduled run is missed or fails (the worker is up but the job never finished) [PRIORITY: MEDIUM]
- [ ] Postgres advisory lock around the daily job so even two workers can never both run it [PRIORITY: LOW]
- [x] Preflight (`python -m scripts.preflight`) and manual run CLI (`python -m scripts.run_pipeline`)
- [x] First real pipeline run (2026-10-27, cloud environment, local Postgres, free chain Gemini → Groq, no Claude key): AAPL, 14/14 agents completed, 13 LLM calls, 0 fallbacks, $0 — BUY 70%
- [ ] Run once with `ANTHROPIC_API_KEY` set, so the chain's last step (Claude Haiku 5.5) and the reasoning model are exercised live too [PRIORITY: MED]
- [ ] The cloud environment's proxy refuses yfinance's news, insider-trade and earnings-date calls (HTTP 403 on the CONNECT): sentiment ran with no headlines and earnings without dates. Check whether production reaches them; if not, take news and insider trades from FMP (`/stable/news/stock`, `/stable/insider-trading`) [PRIORITY: MED]
- [ ] On the FMP free plan, institutional ownership and earnings-call transcripts return 402, so `institutional` and `growth` always answer neutral 0% (weights 5 and 10 contribute nothing): find another source (SEC 13F for holders), or lower their weights until one exists — confirm with backtest A [PRIORITY: MED]
- [x] CI (GitHub Actions): lint, format, bandit, pip-audit / npm audit, pytest on SQLite + PostgreSQL, migration check, Jest, Playwright
- [ ] Protect `main` in GitHub settings: require the CI checks to pass before merging, no direct pushes [PRIORITY: HIGH]
- [x] Dependabot (pip, npm, docker, github-actions), weekly, minor/patch grouped
- [ ] Pin GitHub Actions by commit SHA instead of major tag [PRIORITY: LOW]
- [x] Dockerfiles (backend: API / worker / migrations; frontend: Next standalone), non-root, full Docker Compose stack + CI smoke test
- [ ] Publish images to GHCR and add a deploy workflow [PRIORITY: MED]
- [ ] Pin Docker base images by digest (Dependabot keeps them updated) [PRIORITY: LOW]
- [ ] Make uvicorn's own access/startup logs use the JSON formatter too (`--log-config`) [PRIORITY: LOW]
- [x] Structured logging (`LOG_FORMAT=text|json`): `extra=` fields reach the output, secrets in URLs are scrubbed, httpx URL logging quieted

## API & Frontend
- [x] REST endpoints under /api/v1: agents, symbols overview, latest recommendation, agent results, agent_runs, manual pipeline trigger (202, background)
- [x] Authentication on /api/v1 (X-API-Key, fail-closed in production) + dashboard Basic auth + server-side key proxy with CSRF checks
- [ ] Replace dashboard Basic auth with real login (OIDC / NextAuth) once there is more than one user [PRIORITY: MED]
- [ ] Scoped API keys (read-only vs. can trigger runs) and per-key rate limiting [PRIORITY: LOW]
- [x] One manual pipeline run at a time (409 while a run is active)
- [ ] Persist the 'run active' lock in the DB so it also holds across several backend workers [PRIORITY: LOW]
- [ ] Cursor pagination for /runs and /symbols/{symbol}/results instead of limit-only [PRIORITY: LOW]
- [x] Manage the watchlist through the API (`watchlist` table, `/api/v1/watchlist` add / remove / reorder; WATCHLIST only seeds it once; the scheduler reads it when the job fires)
- [ ] Check that a ticker exists (yfinance quote) when it is added to the watchlist, not only its format [PRIORITY: MED]
- [ ] Watchlist groups / tags (e.g. "core", "ideas") and per-group runs [PRIORITY: LOW]
- [x] Watchlist management in the dashboard: add (format checked client-side, duplicate by the API), move up / down, remove with a confirm step, a 30-run score sparkline per row, an empty state that says when the next run is
- [x] Drag-to-reorder on the watchlist (dnd-kit: grip handle per row, pointer / touch / keyboard, screen-reader announcements; the order moves at once and snaps back if the API refuses)
- [x] Watchlist on phones: below `sm` the row controls fold into one menu per row (Move up / Move down / Remove…, the remove still confirmed)
- [x] Analysis story (`/symbols/{symbol}/story`): one screen per analyst in pipeline order, a "they don't all agree" beat when the signals split, the verdict as the peak; CSS scroll-timeline reveal, static under reduced motion or without support
- [x] Story: each act says what it adds to the score and where it stands; on wide screens a sticky "Running score" aside follows the act being read
- [ ] Story: name the analysts that are not weighted in the score ("not counted") in the opening, so the reader knows before the acts [PRIORITY: LOW]
- [x] Next.js frontend: watchlist, symbol detail, run history; types generated from OpenAPI + Zod validated and checked against them
- [x] Symbol detail: verdict hero with score scale, analyst consensus, contribution waterfall, price chart (SMA20/50, volume, RSI, BUY/SELL markers, range in the URL), per-agent panels (valuation, technicals, fundamentals, earnings, risk, sentiment + generic), score history
- [ ] Expose the BUY / SELL thresholds through the API instead of mirroring them in `frontend/src/lib/scoring.ts` [PRIORITY: LOW]
- [ ] Panels for the remaining agents' own metrics (moat margins, institutional flows, financial-history CAGRs, market scanner) — they use the generic panel today [PRIORITY: LOW]
- [ ] CI: `timeout-minutes` on the "Install Playwright browser" step (it hung twice before any test ran) and cache the browser between runs [PRIORITY: MED]
- [x] Charts: recommendation score history and price history per symbol (`GET /symbols/{symbol}/prices`, `/results?agent=recommendation`)
- [ ] Price chart: weekly bars for ranges over 1Y, and intraday for 1D/5D [PRIORITY: LOW]
- [x] Design system: Hallmark "Console" theme (tokens in globals.css, Host Grotesk + Atkinson Hyperlegible Mono, restyled primitives); mobile header no longer widens the page
- [ ] Light mode: Console's "paper" colourway as a second token set behind `prefers-color-scheme` [PRIORITY: LOW]
- [ ] Run Hallmark's rendered sloplint (`--render --url`) in CI; it needs puppeteer-core + Chrome, so only the static pass runs today [PRIORITY: LOW]
- [ ] Agents page from GET /api/v1/agents (dependency graph + weights) [PRIORITY: LOW]
- [ ] shadcn CLI was unreachable from the build environment — primitives in src/components/ui were written from the shadcn source; re-sync with `npx shadcn add` when online [PRIORITY: LOW]
- [ ] Move to Next.js 16 when CLAUDE.md allows — Next 15 bundles a vulnerable postcss, currently forced to 8.5.31 via npm overrides [PRIORITY: MED]

## LLM
- [x] 10-K excerpts: the opening plus the sentences with moat / risk keywords, at lower budgets (moat 6k→3.5k, risk 8k→4.5k, broad_analysis 8k→4k chars) — about −31% input tokens per symbol
- [ ] Decide on the experiments with a live eval run, then make the winners defaults (presets in backend/evals/presets/): prompts_v2, haiku55 (~10x cheaper), rule_based_quant (−2 calls per symbol), skills, cheap_alt_news [PRIORITY: HIGH]
- [ ] Message Batches API (−50%) for the scheduled daily run, one batch per dependency level — worth it once the daily cost is meaningful (today ≈ $0.15 for 9 symbols) [PRIORITY: LOW]
- [ ] Prompt caching — only pays once a system prompt (+ skills) exceeds the model's minimum cacheable prefix (512 tokens on the 5.5 models, 4096 on Haiku 4.5); today's prompts are 60–250 tokens [PRIORITY: LOW]
- [x] Eval harness (evals/): scenario + ledger-replay suites; label accuracy, confidence limits, stability across repeats, LLM-as-judge faithfulness, contract violations, tokens and cost; cost estimate before every run; reports + compare
- [ ] Run the first live eval baseline (needs ANTHROPIC_API_KEY): current models vs claude-haiku-5-5 / claude-sonnet-5-5, with and without skills [PRIORITY: HIGH]
- [ ] Optional weekly eval in GitHub Actions with a key secret, posting the report as an artifact [PRIORITY: LOW]
- [x] Outcome evals: did the signals predict 1 / 4 / 12-week returns vs SPY — `decision_outcomes` + `evals.run --suite outcomes`
- [x] Agent profiles (provider, model, skills, max_tokens, use_llm, prompt variant) with AGENT_PROFILES overrides; skills in app/llm/skills; OpenAI-compatible second provider; every call through Agent.ask()
- [ ] Decide which skills become defaults per agent — from eval results, not intuition [PRIORITY: MED]
- [ ] Skills with data hooks (e.g. comparable_companies fetching peers) instead of text-only guidance [PRIORITY: LOW]
- [x] Free tiers first: Gemini / Groq / Cerebras with client-side quotas (RPM, TPM, daily limits seeded from the ledger) and a fallback chain ending on Claude Haiku 5.5 (`LLM_PROVIDER=chain`)
- [x] Provider visibility: `llm_calls.provider` in the API, `group_by=provider`, `/llm/providers` (chain order, limits, use today), provider cards on the Tokens & cost page, Grafana provider and chain fall-through panels
- [x] Architecture pass over PRs 1–8: one provider contract (`app/llm/provider.py`) instead of `getattr` in the API / preflight / evals, shared reply handling in `CallTracker`, `LLMError` in `app/llm/errors.py`, the alt provider as a catalog spec, `AnalysisResult.from_judgement` + `knowledge_block` for every agent, shared query states in the frontend
- [ ] Type-check the backend with mypy in CI (strict for `app/llm`) — the provider Protocol is only checked by tests today [PRIORITY: MED]
- [ ] Move the watchlist and recommendation card onto the shared query states (they add Retry / a 404 message, so they need a variant) [PRIORITY: LOW]
- [x] First live eval on Gemini free tier (gemini-3.5-flash-lite, scenario suite): 100% label accuracy on 22 labelled cases, 0 fallbacks, $0 — it surfaced the fundamentals missing-data bug (fixed)
- [ ] Audit the other domain scorers (valuation DCF / owner earnings / EV-EBITDA, financials) for "missing field = 0" defaults, like the fundamentals vote had [PRIORITY: MED]
- [ ] Run the free_gemini preset against a Claude baseline with --repeats 3 --judge once ANTHROPIC_API_KEY is available, then decide the default provider [PRIORITY: HIGH]
- [x] First full live pipeline run (AAPL, MSFT): all 13 agents complete on the free LLM chain at $0, after moving FMP to /stable/, fixing EDGAR's archive URL and adding the Yahoo chart fallback; the valuation no longer divides by a price x 1-share market cap
- [x] Fill yfinance `info` fundamentals from FMP when Yahoo returns only a quote (`FmpClient.get_info_fields`) — live: 26/26 agent runs complete, fundamentals and all three valuation methods on real data
- [ ] FMP budget: ~21 calls per symbol per run (~190/250 for 9 symbols). Share one statements fetch per symbol across agents (they ask for different `limit`s, so the cache misses), or raise the cache TTL to a day for annual statements [PRIORITY: MED]
- [ ] Review the valuation model's calibration: with real data it calls AAPL and MSFT bearish at 95% (intrinsic ~$1.9T vs a $5T market cap) — the 15% DCF haircut and 12x owner-earnings multiple may be too conservative for mega-caps; decide with an outcome eval [PRIORITY: MED]
- [ ] Earnings-call transcripts and institutional ownership need a paid FMP plan, or another source (SEC 13F filings for ownership) [PRIORITY: MED]
- [ ] FMP marks ETFs with isEtf=true and still gives them a sector — skip company-only agents (moat, fundamentals, valuation) for ETFs such as SPY / QQQ [PRIORITY: MED]
- [ ] Alert when a free tier passes 90% of its daily limit (Grafana alert on the "use today" query) [PRIORITY: LOW]
- [ ] Run the free_chain / free_gemini presets against the baseline in a live eval before making the chain the default [PRIORITY: HIGH]
- [ ] More chain steps: OpenRouter `:free` models (50 req/day, 1,000 after a one-time $10 top-up), Mistral's free tier (trains on inputs), a local Ollama [PRIORITY: LOW]
- [ ] Share free-tier quota state between several API replicas (Redis) instead of per-process counters seeded from the ledger [PRIORITY: LOW]
- [ ] Re-read the free-tier limits each quarter: they change often (Gemini cut Pro to ~50/day, Groq dropped Llama from its free tier) [PRIORITY: LOW]
- [x] Upgrade the `anthropic` SDK pin 0.40 → 2.3.0 (API version 2026-10-21); `output_config` / `mcp_servers` are now typed parameters
- [ ] After deploying the SDK 2.x upgrade, run `python -m scripts.preflight` with the real ANTHROPIC_API_KEY to confirm a live request on API version 2026-10-21 [PRIORITY: HIGH]
- [x] LLM ledger (`llm_calls`): tokens, cost, latency, prompt version and exact text of every call; `/api/v1/llm/usage`, Tokens & cost page, `scripts.token_report`
- [ ] Per-day LLM cost budget (like the FMP DailyCallBudget) that stops new calls and alerts when exceeded [PRIORITY: MED]
- [ ] Load model prices from config instead of `app/llm/pricing.py`, so a price change needs no deploy [PRIORITY: LOW]
- [ ] Evaluate newer models (claude-haiku-5-5 / claude-sonnet-5-5) for agent judgements via LLM_DEFAULT_MODEL / LLM_REASONING_MODEL — needs an eval set first [PRIORITY: MED]

## MCP Data Sources (Claude for Financial Advisors plugin)
- [x] MCP connector support in LLMClient / Agent.judge(mcp_servers=...) (app/llm/mcp.py)
- [ ] Wire `mcp_servers` into FundamentalsAgent with one licensed provider (Daloopa or S&P Global/Kensho); token via settings/env [PRIORITY: HIGH]
- [ ] Persist the MCP tool calls Claude made (server, tool, input) on the agent result so runs stay auditable and reproducible [PRIORITY: HIGH]
- [ ] Per-provider rate limiting / call budget for MCP tools (Claude decides when to call them, bypassing app/providers) [PRIORITY: MED]
- [ ] Use Morningstar MCP (fair value, moat rating) as a cross-check in MoatAgent / ValuationAgent [PRIORITY: MED]
- [x] Compliance pass on RecommendationAgent output (app/domain/compliance.py): promissory language fails and is replaced, hype / missing-risk is flagged, disclaimer on every result; shown on the symbol page and the watchlist (per-row Flagged/Replaced marker + disclaimer)
- [x] Run the compliance review on every agent's `reasoning` (AgentRunner → app/agents/compliance.py): promissory text is replaced before storage and knowledge writes, hype is flagged
- [x] Show per-agent compliance markers (Flagged / Replaced) in the frontend agent breakdown table (`compliance_status` on each contribution)
- [x] Tooltip on the Flagged / Replaced marker listing the findings (rule + phrase), in the agent breakdown and the watchlist
- [ ] Touch devices: Radix tooltips don't open on tap — consider a popover for the compliance marker on mobile [PRIORITY: LOW]
- [ ] Re-review results stored before the per-agent compliance gate existed (they have no `compliance` field) [PRIORITY: LOW]
- [ ] Optional LLM second-pass compliance review for subtler issues (cherry-picking, unbalanced framing) the regex rules miss [PRIORITY: LOW]
- [ ] Endpoint / report listing recommendations that were flagged or failed compliance, for review [PRIORITY: LOW]

## Dependencies
- [x] Split requirements: runtime / dev / optional knowledge (OpenViking pulls ~300 packages)
- [x] fastapi 0.115 → 0.162 with starlette 1.10 (0.38.x had 14 known vulnerabilities); removed unused python-jose + bcrypt
- [x] Upgrade the remaining old pin (yfinance 0.2.50 → 1.7.0) with the test suite — anthropic, SQLAlchemy 2.1.6, pandas 3.1 and yfinance done
- [ ] yfinance (still in 1.7.0) calls `DataFrame.rename(..., inplace=True)`, which pandas 3.1 deprecates — harmless warning today; becomes an error with pandas 4, so check before that upgrade [PRIORITY: LOW]
- [ ] Smoke-test the yfinance provider against live Yahoo after the pandas 3 / yfinance 1.7 deploy (`python -m scripts.preflight` + one `run_pipeline AAPL`; Yahoo is not reachable from the CI / dev sandbox). yfinance 1.x fetches through curl_cffi (browser impersonation), not requests [PRIORITY: MED]
- [ ] yfinance 1.x `earnings_dates` gives `Surprise(%)` in percent (4.52), 0.2.50 gave a fraction (0.0452) — nothing reads the column today (surprises come from FMP); scale it if an agent starts using it [PRIORITY: LOW]
- [x] Frontend majors: Jest 30 + jest-dom 7, Next 16 (middleware → proxy), @types/node 26, Tailwind 4 + tailwind-merge 3, TypeScript 6, ESLint 10
- [ ] TypeScript 7 (native Go compiler): its npm package has no classic compiler API yet, and typescript-eslint (`<6.1`) and Next's build type-check need it — upgrade once both support TS 7, and drop its `ignore` in `.github/dependabot.yml` [PRIORITY: LOW]
- [ ] openapi-typescript 7.13 declares `typescript ^5`; an npm `overrides` entry gives it TS 6 (output verified identical) — drop the override when it supports TS 6 [PRIORITY: LOW]
- [ ] ESLint 10: eslint-plugin-react / -import / -jsx-a11y (inside eslint-config-next 16) still declare `eslint ≤9` peers, so `npm ci` prints ERESOLVE peer warnings; their rules were checked to fire under 10. Gone once the plugins widen their peer ranges [PRIORITY: LOW]
- [ ] Dependabot `cooldown` (≥7 days before a new release gets a PR, against poisoned releases), then consider auto-merging patch updates of dev dependencies once CI is green; plus a monthly session for major upgrades. Not enabled: every update still goes through a reviewed PR [PRIORITY: LOW]
- [ ] Unpin aiosqlite (held at 0.20.0, test-only): with SQLAlchemy 2.1.6, 0.22.1 hangs the event loop at teardown after a session is cancelled mid-query (force-close via stop() leaves SQLAlchemy's shielded graceful close pending). Retry when either library fixes it — check with `pytest tests/integration/test_api.py`, and drop its `ignore` in `.github/dependabot.yml` [PRIORITY: LOW]
- [ ] FMP earnings history: the free plan caps `earnings?limit` at 5 (4 reported quarters after the upcoming one), so the earnings agent sees half its 8-quarter window — make the limit a setting (`FMP_EARNINGS_LIMIT`) for paid plans [PRIORITY: LOW]
- [ ] Growth and institutional agents get no transcript / 13F data on the FMP free plan (HTTP 402) — consider a free source for transcripts (e.g. SEC 8-K exhibits) or skip those agents when the plan lacks them [PRIORITY: MEDIUM]
- [ ] Five tests (`test_llm_router.py`, `test_preflight.py`, `test_api.py::test_agents_show_their_effective_profile`) fail when `GEMINI_API_KEY` / `GROQ_API_KEY` / `LLM_PROVIDER` are set in the shell: the test settings read the real environment — isolate them (monkeypatch.delenv in conftest) [PRIORITY: MEDIUM]
