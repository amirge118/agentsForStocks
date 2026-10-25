"""
Evals — measure how reliably the agents judge, and what it costs, for a given
model / provider / prompt / skill configuration. Dev tooling: not in the image.

    python -m evals.run --suite scenarios --repeats 3                  # estimate, then ask
    python -m evals.run --suite scenarios --repeats 3 --yes --label base
    python -m evals.run --profiles '{"*": {"model": "claude-haiku-5-5"}}' --label haiku55 --yes
    python -m evals.compare evals/reports/<a>.json evals/reports/<b>.json
    python -m evals.capture --days 7          # real prompts from the ledger → datasets/ledger.jsonl
"""
