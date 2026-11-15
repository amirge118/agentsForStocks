# Improvement plan after stabilisation (2026-11-15)

The stabilisation check passed (`docs/plans/stabilization.md`): the pipeline runs every night at no
cost and without failures. What isn't known yet is whether its calls are any good: on 2026-11-15 only
14 calls had settled, all at the 5-session horizon, one market week, mostly on stocks that move
together. Hence the order: first what can be done without outcomes, then measure, and only then
change weights, ceilings or the valuation model.

Each step is its own PR. Items refer to `FUTURE_IMPROVEMENTS.md`.

## 1. Without outcomes (November)

**1a. Mark a recommendation built on thin evidence.** When several analysts come back neutral at 0%
with data gaps, the recommendation gets `needs_review` with the reason (section 3: "A recommendation
built on many no-evidence analysts"). In the recommendation's own review reasons
(`app/agents/recommendation.py`): analysts with nothing to judge, or missing, holding 20% of the
weight or more. Done 2026-11-15.

**1b. Round 3 of the recommendation.** The prompt gets each analyst's short reasoning, not only its
signal (planned in `docs/agent-journal.md`). Ships only with an eval report: current vs new
configuration, `evals.run` + `evals.compare`, on the free chain. Done 2026-11-15: faithfulness
50% → 90% (`docs/agent-journal.md`).

Not now: weights, the confidence ceilings, the valuation growth cap. They wait for step 3.

## 2. Portfolio weights (November, separate from 1)

An optional `weight_pct` per watchlist row: a share of the portfolio, never an amount. The dashboard
shows exposure, not advice: the share held in each action (BUY / HOLD / SELL), by sector, and in
symbols whose daily returns move together.

Privacy, enforced by tests:
- weights never reach a prompt: the free Gemini tier may use prompts to improve its products;
- never in logs, never in the repository (it is public): the local database only;
- PR screenshots use the E2E mocks, not real data.

## 3. Measure (from early December, once 20 sessions have settled)

`scripts.track_report --horizon 20` and `scripts.backtest_weights`, then:
- the confidence ceilings 60 / 50 / 25 against outcomes;
- quality vs price: do overvalued BUYs lag the benchmark? If so, test a valuation cap like the risk cap;
- the valuation growth cap for small, young companies;
- bearish calls on fast-rising small caps: in the first week three of them rose 17–29%.

One change at a time, only on a clear out-of-sample win, each with an eval report.

## What waits
- Paid models: the free chain works at $0.
- Section 6 (new capabilities).
- A server instead of the laptop: a missed night isn't critical (the next run sees the missed day's prices).
