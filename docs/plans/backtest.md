# Plan: Backtest of the recommendation over a ticker × date grid

Status: part A implemented (`app/domain/backtest.py`, `scripts/backtest_weights.py`); B waits for the point-in-time guard. Builds on outcome settlement (`docs/plans/outcome-settlement.md`).
Idea source: TradingAgents `tradingagents/backtest.py` (Apache-2.0).

## Goal

Answer, with numbers, whether the pipeline's recommendations beat the benchmark, and which
weights (`@register_agent(recommendation_weight=...)`) and BUY/SELL thresholds
(`app/domain/scoring.py`) would have done better. **Decision quality only**: hit rate and
alpha captured per call. Not a portfolio simulator: no quantities, fills, cash or costs.
Each (ticker, date) cell is independent.

## What already exists

- `decision_outcomes`: the forward return and alpha of every judged (symbol, day) at 5/20/60
  sessions, settled nightly.
- `domain/outcomes.py`: `is_hit`, `captured_alpha`, the hold band.
- `evals.run --suite outcomes`: replays recommendation prompts captured on real days and
  scores a configuration against the alpha that followed. This is the cheap backtest, with
  no look-ahead, but it only covers days the system actually ran.

## Two backtests, cheapest first

### A. Re-weighting stored results (no LLM, no new data)

The analyst results of every day are already stored. For each settled day, recompute
`weighted_score` with candidate weights and thresholds (pure functions in `domain/scoring.py`)
and score the rule-based action against the stored alpha. Thousands of configurations run in
seconds.

- `app/ops/backtest.py`: `grid(weights_grid, thresholds_grid, horizon)` → rows of
  (config, n, hit rate, mean alpha captured, alpha captured by action).
- `scripts/backtest_weights.py --horizon 20 [--since]` prints the top configurations and the
  current one.
- Guard against overfitting: split by date (fit on the first 70% of days, report the last
  30%), and report the current weights next to the best ones. Change weights only on a
  clear, out-of-sample win.

### B. Re-running the pipeline on past dates (needs point-in-time data)

To cover days the system never ran, run the agents with `run_date` in the past. Today the
providers return *current* data (yfinance `info`, latest news, latest 10-K, FMP TTM figures),
so this would leak the future into the past. It needs the point-in-time guard first
(FUTURE_IMPROVEMENTS → Agents):

- clamp every provider call to `run_date` (history `end`, statements filed by `run_date`,
  news published before it);
- withhold live-only snapshots (`info`, current institutional holders) from historical runs,
  and record them as data gaps;
- report "the feed can't reach that window" as unavailable, not empty.

Then: `scripts/backtest_grid.py --symbols AAPL MSFT --start 2026-01-05 --end 2026-06-30
--every 5 --agents ...`, writing to a separate database (never mixed with live results),
then `settle_outcomes` on it and the same reports as A. Cost: about 15 model calls per cell,
so estimate before running, as `evals.run` does, and default to the free chain.

## Tests

- A: a synthetic stored history where one weighting is right by construction; the date
  split; the current configuration always reported.
- B: every provider refuses or trims data after `run_date` (one test per provider); a grid
  run on a fake clock never reads a later date.

## Order

1. A (re-weighting): small, useful as soon as a few weeks have settled.
2. The point-in-time guard (its own PR, one provider at a time).
3. B (grid re-runs).
