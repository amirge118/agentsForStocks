# Plan: Outcome settlement and lessons (closing the loop)

Status: phases 1, 3 and 4 implemented; phase 2 (read side) deferred to FUTURE_IMPROVEMENTS.md. Idea source: TradingAgents (`tradingagents/memory/settlement.py`,
`reflection.py`, `backtest.py`, Apache-2.0); adapted to our runner, ledger and DB.

## Problem

Every weekday we store a BUY / HOLD / SELL per symbol and a signal per agent, and never
check whether any of them was right. Three things are missing because of it:

- **No track record.** We cannot say whether the recommendation, or any single agent,
  beats the market. The weights in `@register_agent(recommendation_weight=...)` and the
  BUY/SELL thresholds in `app/domain/scoring.py` are guesses.
- **No real memory.** `knowledge_block(memory)` only gets what OpenViking recalls, and
  OpenViking is off by default (`NullKnowledgeStore`). Even when it is on, it stores run
  summaries ("cases"), not what happened afterwards.
- **No ground truth for evals.** `evals/` scores label accuracy on hand-labelled scenarios;
  it cannot score against realised returns.

## Goal

1. Settle each stored decision against realised prices: forward return, benchmark return,
   alpha, hit/miss, at several horizons. No LLM, deterministic, idempotent.
2. Turn settled recommendations into short lessons (one cheap LLM call each) and feed them
   to later recommendation runs, strictly point-in-time.
3. Expose the track record (API, dashboard, `scripts`), per agent and per action.

Out of scope here: the grid backtest (TradingAgents #2) and per-agent weight tuning. Both
build on the table from step 1 and get their own plans.

## Design

### 1. Forward returns are per symbol and date, not per agent

The price outcome of "symbol S, decided on day D, held H trading days" is the same for every
agent. So we store prices once and join to `agent_results` to score any agent:

**Table `decision_outcomes`** (migration `0005_decision_outcomes.py`)

| column | type | notes |
|---|---|---|
| id | str (uuid) | PK |
| symbol | str | indexed |
| decision_date | date | the `run_date` of the results being scored |
| horizon_days | int | trading days held: 5, 20, 60 (config) |
| benchmark | str | `SPY` for US; resolved by suffix map later (`.TA` → `TA35.TA`, ...) |
| status | str | `pending` / `settled` / `unavailable` |
| entry_date, exit_date | date | nullable until settled |
| entry_price, exit_price | float | adjusted closes |
| raw_return, benchmark_return, alpha | float | fractions, nullable until settled |
| attempts | int | price-fetch failures; `unavailable` after N (delisted, bad symbol) |
| settled_at | datetime(tz) | nullable |

Unique `(symbol, decision_date, horizon_days)` → upsert, same as `agent_results`.

Scoring rules (pure, `app/domain/outcomes.py`):
- **Entry = the first close after `decision_date`.** The pipeline runs at 18:30 ET, but a
  manual run can happen intraday, so the decision-day close may not have been known.
- **Settle only on a complete window.** Fewer than `horizon + 1` sessions after entry →
  stays `pending`, retried next night. Never settle on a partial return.
- Benchmark valued `asof` the stock's entry/exit sessions, so both returns span the same dates.
- Adjusted closes (`auto_adjust=True`, yfinance default) so splits and dividends don't
  show up as returns.
- Hit: bullish → `alpha > 0`; bearish → `alpha < 0`; neutral/HOLD →
  `|alpha| <= HOLD_BAND` (default 2% at 20 days, scaled by `sqrt(h/20)`). Not stored —
  computed at query time so the band can change without a migration.

### 2. Settlement job (no LLM)

`app/pipeline/settlement.py` — `OutcomeSettler(session_factory, yfinance, settings)`:
1. Seed: for every `(symbol, run_date)` in `agent_results` with no outcome rows, insert
   `pending` rows for each horizon. Covers all history, so the first run backfills.
2. For each symbol with pending rows: one `get_closes(symbol, start, end)` call covering all
   its pending windows, plus one for the benchmark (shared across symbols, TTL cache).
3. Score with `app/domain/outcomes.py`, upsert, commit per symbol (an interruption keeps
   what finished).

Prices go through a new `YFinanceClient.get_closes(symbol, start, end)` (rate limit, retry,
cache, as rule 5 requires). Runs as the first step of `run_daily_pipeline` (scheduler),
before the agents, so today's lessons can see yesterday's settlements. Also callable on its
own: `python -m scripts.settle_outcomes [--since 2026-01-01]`. Wrapped in a
`tracer.start_as_current_span("outcomes.settle")`; counters `outcomes_settled_total` /
`outcomes_unavailable_total` in `app/observability/metrics.py`.

### 3. Lessons: an agent, so it inherits everything

Writing lessons from a script would bypass the runner and miss what agents get for free:
idempotency, `agent_runs`, the `llm_calls` ledger, contracts, compliance review, prompt
snapshots, profiles (so it can run on the free chain). So lessons come from an agent:

**`OutcomeReviewAgent`** (`app/agents/outcome_review.py`, `@register_agent("outcome_review",
recommendation_weight=0)`, no dependencies):
- `fetch`: recommendation outcomes for this symbol settled at the 20-day horizon since its
  last review (at most 3 per run, oldest first), each with the stored recommendation's
  action, confidence, score and reasoning.
- `analyze`: none to review → neutral result with no LLM call. Otherwise one
  `self.ask(..., prompt_name="outcome_review")` per outcome with the prompt in
  `app/llm/prompts/outcome_review.md`: 2–4 plain sentences — what the alpha says about the
  call (cite it; say so when 20 days is too short to judge the thesis), which part of the
  reasoning held or failed, one concrete lesson. Fallback without LLM: a templated sentence
  with the numbers.
- Result: `OutcomeReviewResult(lessons=[{decision_date, action, alpha, resolved_on, text}])`.
- Invariant (`contracts.py`): every lesson quotes its alpha's sign correctly.

**Recall in the recommendation, point-in-time:** `RecommendationAgent.fetch` reads the
latest lessons with `resolved_on <= run_date` — up to 5 for the same symbol and 2 from
other symbols — and the prompt gets a "Track record" block: hit rate of past
recommendations for this symbol at 20 days, plus the lessons. Placed before
`knowledge_block(memory)`; it does not replace OpenViking. The `as_of` filter matters for
any rerun or backtest of a past date.

This is a prompt change → `recommendation` prompt snapshot update + an eval report
(current vs. with track record), per CLAUDE.md rule 16.

### 4. Read side

- `OutcomeRepository.track_record(agent: str | None, horizon, since)` → per agent and
  signal: n, hit rate, mean/median alpha, a confidence-bucket table (does 80% confidence
  beat 50%?). One SQL join `decision_outcomes` ⋈ `agent_results` on `(symbol, run_date)`.
- `GET /api/v1/outcomes/track-record?horizon=20&since=...` and
  `GET /api/v1/symbols/{symbol}/outcomes` (schemas in `app/schemas/outcomes.py`; OpenAPI
  export + `npm run generate:api`).
- Frontend: a "Track record" card on the symbol page (past calls, alpha, hit/miss) and a
  `/track-record` page (per-agent hit rate and alpha by horizon), using the shared query states.
- `python -m scripts.track_report [--horizon 20] [--by agent|action|symbol]`, like `token_report`.

## Phases (each one a PR, CI green)

1. **Settlement**: migration, model, repository, `domain/outcomes.py`, `get_closes`,
   `OutcomeSettler`, scheduler step, `scripts/settle_outcomes`. Useful alone: data starts
   accumulating, history is backfilled.
2. **Read side**: `track_record` query, two endpoints, `track_report` script, symbol card +
   page.
3. **Lessons**: `OutcomeReviewAgent`, prompt, invariant, recall block in the
   recommendation, snapshots, eval report.
4. **Follow-ups**: outcome eval suite in `evals/` (score a configuration's labels against
   realised alpha), then the backtest plan (weights/thresholds).

As built (phases 1, 3, 4):
- Lessons: `app/agents/outcome_review.py` (`OutcomeReviewAgent`, `SessionOutcomesReader`),
  read by agents through `AgentContext.outcomes`; the recommendation depends on it so today's
  lessons are in today's prompt.
- Outcome evals: `evals.capture --outcomes` joins `llm_calls` → `agent_runs` →
  `decision_outcomes`, so a case is the exact prompt of that day plus the alpha that followed;
  `evals.run --suite outcomes` grades `outcome_hit_rate` and `alpha_captured`.
- Backtest: `docs/plans/backtest.md`.

## Tests

- `tests/unit/domain/test_outcomes.py`: entry is the next close; partial window → pending;
  different calendars (benchmark holiday); split-adjusted series; HOLD band; zero/NaN closes
  dropped.
- `tests/unit/pipeline/test_settlement.py` (fake yfinance): backfill seeding, idempotent
  rerun, failure → `attempts` up then `unavailable`, commit per symbol.
- `tests/unit/agents/test_outcome_review.py` through `AgentRunner` with `FakeLLM`: nothing to
  review → no LLM call; lessons stored; fallback without LLM; invariant.
- Recommendation: lessons with `resolved_on > run_date` never reach the prompt (look-ahead
  test); prompt snapshot.
- Integration: endpoints + OpenAPI contract; Postgres migration up/check/down in CI.

## Open questions

1. **Horizons**: 5 / 20 / 60 trading days? The existing "Outcome evals" item says 1 / 4 / 12
   weeks, which is the same thing.
2. **Benchmark**: SPY for everything, or sector ETFs (XLK, XLV, ...) as a second, tougher
   benchmark? Sector-relative alpha separates stock picking from sector beta.
3. **Lesson cost**: one call per settled recommendation (≈ 9 symbols/day → 9 calls/day,
   ≈ 0 on the free chain). Only review misses plus large hits instead?
4. **Lessons beyond the recommendation**: give each analyst agent its own hit rate in its
   prompt? Easy once phase 2 exists, but needs an eval to show it helps.
