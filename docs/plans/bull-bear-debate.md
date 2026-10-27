# Plan: Bull/bear debate before the recommendation

Status: plan, not started. Ship only if an eval beats the current recommendation prompt.
Idea source: TradingAgents `agents/researchers/` and `agents/managers/research_manager.py`
(Apache-2.0).

## Idea

Today the recommendation sees the analysts' signals and makes one call. In TradingAgents a
bull researcher and a bear researcher each argue from the analyst reports, answer each other
for N rounds, and a manager decides. The manager's prompt contains the line worth keeping:
*"conflict alone is not a reason to Hold"*: commit to the side with the stronger case, and
hold only when the evidence is balanced or too thin.

## Design (smallest version that can be measured)

Inside `RecommendationAgent`, as a prompt variant selected by profile (no new agent, no new
table):

1. `ask(prompt_name="recommendation_bull")`: the strongest evidence-based case for buying,
   from the same analyst table and reasoning (max ~600 characters).
2. `ask(prompt_name="recommendation_bear")`: the strongest case against, answering the
   bull's points.
3. `judge(prompt_name="recommendation", prompt=... + both cases)` with
   `recommendation_v3.md`, which adds the "conflict is not a reason to HOLD" rule.

One round only (3 calls instead of 1). The risk cap and compliance stay as they are: they
run in code after the judgement. Both cases are kept on the result (`debate: {bull, bear}`)
for the symbol page and for faithfulness checks. With `use_llm=false` for the
`recommendation_bull`/`_bear` prompts the variant falls back to today's single call.

## How it is decided

- `evals/presets/debate.json`: `{"recommendation": {"prompt": "recommendation_v3"}, ...}`.
- Run the scenario suite (labels, stability, faithfulness) and **the outcome suite**
  (`evals.run --suite outcomes`: hit rate and alpha captured against what really followed)
  on the current and the debate configuration, then `evals.compare`.
- Adopt only if the outcome hit rate or alpha captured improves on enough settled cases, at
  an acceptable cost (3× the recommendation calls; on the free chain this is mostly quota).

## Risks

- Longer prompts and three times the calls for the most expensive (reasoning-model) agent.
- Models tend to "split the difference" after a debate; the v3 rule and the eval guard this.
- Invariant to add: a HOLD after the debate must name why the evidence is balanced.
