# CLAUDE.md — agentsForStocks

> Canonical rules for Claude Code. Read this first on every session.

## Quick Start

```bash
# Backend (FastAPI on :8000)
cd backend && uvicorn app.main:app --reload

# Frontend (Next.js on :3000)
cd frontend && npm run dev

# Run all backend tests
cd backend && pytest

# Run all frontend tests
cd frontend && npm test

# Run E2E tests
cd frontend && npm run test:e2e
```

## Architecture in One Paragraph

Frontend (Next.js 15 App Router) talks to Backend (FastAPI) via JSON REST under `/api/v1/`. Frontend has zero business logic and zero direct DB access. Backend layers: HTTP router → Pydantic schemas → Services → Agent Orchestrator → Data Pipeline → Models/DB/external APIs. Stock data comes from `yfinance`. AI analysis uses Anthropic Claude via `anthropic` SDK. Agents are scheduled tasks that are idempotent, store all results in PostgreSQL, and expose their output via REST endpoints.

## Non-Obvious Gotchas (Read Before Writing Code)

### 1. Mandatory Request/Response Logging (backend)
Every new backend API endpoint MUST be covered by the logging middleware. Reference: `backend/app/middleware/request_logging.py`. Redacts: `password`, `token`, `secret`, `api_key`, `authorization`. Log level: INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx.

### 2. FUTURE_IMPROVEMENTS.md is Mandatory
For every feature request, improvement idea, or "nice to have" identified during implementation: add it to `FUTURE_IMPROVEMENTS.md` at the repo root. Use `- [ ] Description [PRIORITY]`. Never skip this.

### 3. Async SQLAlchemy 2.0 Patterns
Use `select()` (not `query()`). Use `AsyncSession` injected via `Depends(get_db_session)`. Use `selectinload`/`joinedload` for eager loading. **Test DB uses `sqlite+aiosqlite:///:memory:`** — do NOT assume PostgreSQL in tests. See `backend/tests/conftest.py` for fixture pattern.

### 4. Agent Idempotency — Non-Negotiable
Every agent run MUST be idempotent. Use `upsert` (insert-or-update) patterns when writing results to DB. Agents must not duplicate records if re-run for the same symbol + date. Store `run_id`, `agent_type`, `symbol`, `run_at` on every result row.

### 5. External API Rate Limiting
All calls to `yfinance`, financial APIs, or any external service MUST go through a wrapper with:
- Exponential backoff + retry (3 attempts, 1s/2s/4s)
- Per-domain rate limiting
- Timeout of 10s max per request
Reference: `backend/app/services/external_api_base.py` (create this early, reuse everywhere).

### 6. TanStack Query v5 Patterns
Use `isPending` for loading skeletons (NOT `isLoading` — that's v4). Get query client via `useQueryClient()` hook. On mutation success: `invalidateQueries`. On mutation error: `toast({ variant: "destructive" })`.

### 7. No Direct `fetch` in Components
Use `get`/`post`/`put`/`del` from `@/lib/api/client.ts`. Never call `fetch()` directly from components or hooks.

### 8. Finance Number Formatting
- Currency: `toLocaleString("en-US", { style: "currency", currency: "USD" })`
- Percentages: `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`
- Prices: `font-mono` class; numeric tables: `tabular-nums`
- Gain: `text-green-400` / `bg-green-400/10`. Loss: `text-red-400` / `bg-red-400/10`

## Key File Map

| What you need | Where |
|---|---|
| Agent orchestration logic | `backend/app/agents/` |
| Agent base class + idempotency helpers | `backend/app/agents/base.py` |
| External API wrapper (rate limit, retry) | `backend/app/services/external_api_base.py` |
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
    agents/           # Agent classes (one file per agent type)
      base.py         # AgentBase: run(), store_result(), idempotency check
      scheduler.py    # APScheduler or similar — registers and triggers agents
    api/v1/endpoints/ # FastAPI routers
    services/         # Business logic + external_api_base.py
    schemas/          # Pydantic request/response models
    models/           # SQLAlchemy models (include AgentRun, AgentResult)
    middleware/       # request_logging.py, error_handler.py
  tests/
    unit/             # pytest unit tests (mock all external deps)
    integration/      # pytest integration tests (test API endpoints)

frontend/
  app/                # Next.js App Router pages (keep thin)
  components/
    features/         # Domain components (agents/, stocks/, dashboard/)
    ui/               # Shadcn primitives (never hand-roll)
  lib/
    api/              # client.ts base + per-domain query files
    hooks/            # Custom React hooks
  types/              # TypeScript interfaces for API responses
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

## Testing Requirements

- Backend: pytest, 80%+ coverage, `@pytest.mark.asyncio`, mock yfinance and all external APIs.
- Frontend: Jest + React Testing Library, test loading/error/success states. Playwright for E2E.
- Pyramid: 70% unit / 20% integration / 10% E2E.
- Every new file under `backend/app/` MUST have a corresponding test file before merging.
- Coverage must remain ≥ 80% (enforced by `--cov-fail-under=80`).
- Never mark a feature complete without tests.
- Agent tests: mock the scheduler and assert on DB state after `agent.run()`.

## Commit Format

```
<type>(<scope>): <subject>
```
Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`
Scopes: `agents`, `stocks`, `scheduler`, `api`, `frontend`, `db`, `infra`
Example: `feat(agents): add MarketScannerAgent with sector rotation logic`
