# CLAUDE.md — agentsForStocks

> Canonical rules for Claude Code. Read this first on every session.

## Language Rules

Detailed coding standards are in `.claude/rules/` — Claude enforces these automatically:
- Python: `.claude/rules/python.md` (types, logging, secrets, testing, bandit)
- TypeScript: `.claude/rules/typescript.md` (Zod, no-any, repository pattern, no console.log)

## Quick Start

```bash
# Whole stack in Docker (db → migrate → api + worker → frontend); needs .env
docker compose up --build

# ... plus monitoring: Grafana with traces, metrics, logs and the agents dashboard (:3001)
# (set OTEL_ENABLED=true in .env)
docker compose --profile observability up --build

# Backend dependencies (runtime + test/lint tools; add requirements-knowledge.txt for OpenViking)
cd backend && pip install -r requirements-dev.txt

# Backend (FastAPI on :8000)
cd backend && uvicorn app.main:app --reload

# Frontend (Next.js on :3000)
cd frontend && npm run dev

# Apply DB migrations
cd backend && alembic upgrade head

# Before a real run: check keys + connectivity to Claude, FMP, Yahoo, SEC (exit 1 = not ready)
cd backend && python -m scripts.preflight

# Run the pipeline once, now (all agents, or a subset)
cd backend && python -m scripts.run_pipeline AAPL MSFT [--agents technicals valuation] [--force]

# Token usage and cost per agent / model / day / prompt version (from the llm_calls ledger)
cd backend && python -m scripts.token_report [--days 30] [--by model]

# Production scheduler: API processes with RUN_SCHEDULER=false + exactly one worker
cd backend && python -m app.worker

# Run all backend tests (coverage gate: 80%; set TEST_POSTGRES_URL to include the Postgres tests)
cd backend && pytest

# Run all frontend tests (type-check, lint, unit)
cd frontend && npm run typecheck && npm run lint && npm test

# Run E2E tests
cd frontend && npm run test:e2e
```

## Architecture in One Paragraph

Frontend (Next.js 15 App Router) talks to Backend (FastAPI) via JSON REST under `/api/v1/`. Frontend has zero business logic and zero direct DB access. Backend layers: HTTP router → Pydantic schemas → `pipeline/` orchestrator → `agents/` (via `AgentRunner`) → `domain/` (pure financial logic) + `providers/` (yfinance, FMP, SEC EDGAR) + `llm/` (Claude) → `repositories/` → models/DB. Dependencies are wired once in `app/container.py` and injected through `AgentContext`. Agents run once per weekday as a dependency graph (registry), are idempotent, and store typed results in PostgreSQL.

## Non-Obvious Gotchas (Read Before Writing Code)

### 1. Mandatory Request/Response Logging (backend)
Every new backend API endpoint MUST be covered by the logging middleware. Reference: `backend/app/middleware/request_logging.py`. Redacts: `password`, `token`, `secret`, `api_key`, `authorization`. Log level: INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx.

### 2. FUTURE_IMPROVEMENTS.md is Mandatory
For every feature request, improvement idea, or "nice to have" identified during implementation: add it to `FUTURE_IMPROVEMENTS.md` at the repo root. Use `- [ ] Description [PRIORITY]`. Never skip this.

### 3. Async SQLAlchemy 2.0 Patterns
Use `select()` (not `query()`). Use `AsyncSession` injected via `Depends(get_db_session)`. Use `selectinload`/`joinedload` for eager loading. **Test DB uses `sqlite+aiosqlite:///:memory:`** — do NOT assume PostgreSQL in tests. See `backend/tests/conftest.py` for fixture pattern.

### 4. Agent Idempotency — Non-Negotiable
Every agent run MUST be idempotent. `AgentRunner` enforces it: it skips an (agent, symbol, market date) that already has a result and writes through `AgentResultRepository.upsert`. Never write results from inside an agent. Every execution (including failures) is also recorded in `agent_runs`. Use `market_today()` from `app/core/clock.py`, never `date.today()`.

### 5. External API Rate Limiting
All calls to `yfinance`, financial APIs, or any external service MUST go through `app/providers/` (`HttpClient` / `YFinanceClient`), which provide:
- Exponential backoff + retry on transient errors only (3 attempts, 1s/2s/4s)
- Per-domain rate limiting (`RateLimiter`, limits in `app/container.py`)
- Timeout of 10s max per request, plus a TTL cache shared by all agents
FMP calls also count against `DailyCallBudget` (free tier = 250/day). Claude is called only through `app/llm/client.py` (structured outputs).

### 11. Every LLM Call Is Measured — Keep It That Way
`LLMClient.generate` records each request (success or failure) in `llm_calls`: tokens, cost (`app/llm/pricing.py` — add a price when you add a model), latency, `prompt_version` (hash of the system prompt) and, with `LLM_CAPTURE_CONTENT=true`, the exact prompt and reply. Always pass `prompt_name=`; agents go through `Agent.judge()`, which does. On `LLMError`, call `note_fallback()` so the run's `llm_fallbacks` is counted.

### 14. Agent Contracts and Prompt Snapshots
`AgentRunner` checks every result (`app/agents/contracts.py`): `data_gaps` lists inputs that came back empty (and `judge()` tells Claude about them), confidence is capped at 25% when *all* inputs are empty, and per-agent rules declared with `@register_agent(invariants=...)` are recorded in `contract_violations`. When a prompt states a rule, add an invariant for it. Hard business rules (the risk cap on the recommendation) are enforced in code, not left to the prompt. Prompts are snapshotted in `tests/snapshots/prompts/`; after an intended prompt change run `UPDATE_SNAPSHOTS=1 pytest tests/unit/agents/test_prompt_snapshots.py` and commit the diff. Golden scenarios (company archetypes) live in `tests/scenarios.py`.

### 13. Observability (OpenTelemetry)
`app/observability/telemetry.py` installs tracing, metrics and log export only when `OTEL_ENABLED=true`; otherwise every span and metric is a no-op, so tests need nothing. New long-running work → wrap it in `tracer.start_as_current_span(...)`; new counters/histograms go in `app/observability/metrics.py`. Exact figures (tokens, cost, run counts) come from the DB ledger, not from Prometheus: `increase()` drops a series' first sample.

### 12. Run Context in Logs
`AgentRunner` and `PipelineOrchestrator` bind `pipeline_run_id` / `run_id` / `agent` / `symbol` in contextvars (`app/core/context.py`); `ContextFilter` adds them to every log line. Don't pass these ids through `extra=` by hand. Log extras are redacted by whole word (`api_key`, `access_token`), so `input_tokens` stays readable.

### 6. TanStack Query v5 Patterns
Use `isPending` for loading skeletons (NOT `isLoading` — that's v4). Get query client via `useQueryClient()` hook. On mutation success: `invalidateQueries`. On mutation error: `toast({ variant: "destructive" })`.

### 7. No Direct `fetch` in Components
Use `get`/`post`/`put`/`del` from `@/lib/api/client.ts`. Never call `fetch()` directly from components or hooks.

### 10. Authentication
- Backend: every `/api/v1` route requires `X-API-Key` (keys in `API_KEYS`, checked in `app/api/auth.py`; `/health` is public). `ENVIRONMENT=production` refuses to start without keys. New routers go under `api_router`, so they inherit the check.
- Frontend: the browser never sees the key. It calls the same-origin proxy `src/app/api/backend/[...path]/route.ts`, which adds `BACKEND_API_KEY` from server-only env (`src/lib/server/env.ts`, `import "server-only"`). The dashboard itself is protected by Basic auth in `src/middleware.ts` (`DASHBOARD_PASSWORD`; required under `next start`).
- The proxy only forwards writes that are same-origin and `application/json` (CSRF protection — Basic-auth credentials are sent by the browser automatically).

### 9. API Contract Workflow
After changing a backend schema or route: `cd backend && python -m scripts.export_openapi`, then `cd frontend && npm run generate:api`. `tests/integration/test_openapi_contract.py` fails while `frontend/openapi.json` is stale, and `npm run typecheck` fails while a Zod schema in `src/types/api.ts` no longer matches the generated types.

### 8. Finance Number Formatting
- Currency: `toLocaleString("en-US", { style: "currency", currency: "USD" })`
- Percentages: `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`
- Prices: `font-mono` class; numeric tables: `tabular-nums`
- Gain: `text-green-400` / `bg-green-400/10`. Loss: `text-red-400` / `bg-red-400/10`

## Key File Map

| What you need | Where |
|---|---|
| Agent classes (one file per agent) | `backend/app/agents/` — register in `agents/catalog.py` |
| Agent contract / run lifecycle | `backend/app/agents/base.py` / `backend/app/agents/runner.py` |
| Agent registry (deps, weights, order) | `backend/app/agents/registry.py` |
| Pipeline orchestration + scheduler | `backend/app/pipeline/orchestrator.py`, `backend/app/agents/scheduler.py`, `backend/app/worker.py` |
| Preflight / manual runs | `backend/app/ops/`, `backend/scripts/preflight.py`, `backend/scripts/run_pipeline.py` |
| Pure financial logic | `backend/app/domain/` |
| External data clients (rate limit, retry, cache) | `backend/app/providers/` |
| Claude client + system prompts | `backend/app/llm/client.py`, `backend/app/llm/prompts/*.md` |
| Remote MCP data sources (FactSet, S&P, ...) | `backend/app/llm/mcp.py` → `Agent.judge(mcp_servers=...)` |
| DB access | `backend/app/repositories/` |
| Dependency wiring | `backend/app/container.py` |
| Migrations | `backend/alembic/` (`alembic upgrade head`) |
| FastAPI routers | `backend/app/api/v1/endpoints/` |
| Pydantic schemas | `backend/app/schemas/` |
| SQLAlchemy models | `backend/app/models/` |
| Logging middleware | `backend/app/middleware/request_logging.py` |
| Frontend API client | `frontend/src/lib/api/client.ts` |
| Frontend custom hooks | `frontend/src/lib/hooks/` |
| TypeScript response types | `frontend/src/types/` |

## Directory Conventions

```
backend/
  app/
    agents/           # One file per agent + base.py, runner.py, registry.py, catalog.py, scheduler.py
    pipeline/         # orchestrator.py — runs the agent dependency graph per symbol
    domain/           # Pure functions: valuation, technicals, scoring, ... (no I/O)
    providers/        # yfinance / FMP / EDGAR clients + http, retry, rate_limit, cache
    llm/              # LLMClient + prompts/<agent>.md
    knowledge/        # KnowledgeStore protocol, OpenViking + null implementations
    repositories/     # SQL lives here only
    api/v1/endpoints/ # FastAPI routers
    schemas/          # Pydantic request/response models
    models/           # SQLAlchemy models (AgentResult, AgentRun)
    middleware/       # request_logging.py
    container.py      # Composition root
  tests/
    unit/             # pytest unit tests (mock all external deps)
    integration/      # pytest integration tests (test API endpoints)

frontend/
  openapi.json        # API contract, exported from the backend (python -m scripts.export_openapi)
  src/
    app/              # Next.js App Router pages (keep thin)
    components/
      features/       # Domain components (agents/, stocks/, dashboard/)
      ui/             # Shadcn primitives (never hand-roll)
    lib/
      api/            # client.ts (only place with fetch) + repositories.ts + repository-context
      hooks/          # TanStack Query hooks (queries.ts) + use-toast
    types/            # openapi.d.ts (generated) + api.ts (Zod schemas, checked against it)
  e2e/                # Playwright specs (API mocked with page.route)
```

## Dark Theme Tokens

| Token | Use |
|---|---|
| `bg-zinc-950` | Page canvas |
| `bg-zinc-900` | Cards, panels |
| `bg-zinc-800` | Table headers, hover, inputs |
| `border-zinc-800` | Card borders |
| `text-zinc-400` | Secondary / labels |
| `text-green-400` / `text-red-400` | Gain / loss |
| `bg-green-400/10` / `bg-red-400/10` | Gain / loss badge backgrounds |

Card pattern: `rounded-xl border border-zinc-800 bg-zinc-900`

## CI

`.github/workflows/ci.yml` runs on every push to main and every PR — keep it green:
- **backend**: ruff, black, bandit, pip-audit, pytest (SQLite + a PostgreSQL 16 service; deprecation warnings are errors), `alembic upgrade/check/downgrade` on Postgres.
- **frontend**: `npm ci`, generated API types up to date, typecheck (Zod ↔ OpenAPI), lint, `npm audit`, Jest with coverage, Playwright E2E on the production build.
- **docker**: builds both images and brings the whole stack up with Docker Compose, then smoke-tests health, auth, the proxy and a manual run.
Dependabot (`.github/dependabot.yml`) opens weekly update PRs for pip, npm, Docker base images and GitHub Actions.
Run the same commands locally before pushing.

## Testing Requirements

- Backend: pytest, 80%+ coverage, `@pytest.mark.asyncio`, mock yfinance and all external APIs.
- Frontend: Jest + React Testing Library, test loading/error/success states. Playwright for E2E.
- Pyramid: 70% unit / 20% integration / 10% E2E.
- Every new file under `backend/app/` MUST have a corresponding test file before merging.
- Coverage must remain ≥ 80% (enforced by `--cov-fail-under=80`).
- Never mark a feature complete without tests.
- Agent tests: build agents with `tests/factories.make_context()` (fake providers + `FakeLLM`); test the run lifecycle through `AgentRunner` and assert on DB state.
- Concurrent pipeline tests must use the `concurrent_session_factory` fixture (the in-memory DB shares one connection between sessions).

## Commit Format

```
<type>(<scope>): <subject>
```
Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`
Scopes: `agents`, `stocks`, `scheduler`, `api`, `frontend`, `db`, `infra`
Example: `feat(agents): add MarketScannerAgent with sector rotation logic`
