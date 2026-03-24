# Python Rules — agentsForStocks

Enforced automatically on every `.py` file. No exceptions.

## Style & Formatting

- **PEP 8** compliance is mandatory
- **Type annotations** on every function signature — parameters and return types
- **Black** for formatting, **ruff** for linting — both must pass before any commit
- Use `@dataclass(frozen=True)` for immutable data structures (e.g., agent configs, result DTOs)
- Use `NamedTuple` for lightweight read-only records

```python
# Good
@dataclass(frozen=True)
class StockResult:
    symbol: str
    price: float
    analyzed_at: datetime

# Bad — mutable dict, no types
result = {"symbol": "AAPL", "price": 150}
```

## Logging

- **Never use `print()`** — use the `logging` module exclusively
- Log level conventions: `DEBUG` for internals, `INFO` for agent lifecycle events, `WARNING` for retries, `ERROR` for failures
- Every agent run must log start, finish, and any errors with the `symbol` and `run_id` in context

```python
import logging
logger = logging.getLogger(__name__)

# Good
logger.info("Agent started", extra={"symbol": symbol, "run_id": run_id})

# Bad
print(f"Agent started for {symbol}")
```

## Secrets & Environment

- **Never hardcode** API keys, passwords, or tokens
- Always use `os.environ["KEY"]` — let it raise `KeyError` if missing (fail fast)
- Load `.env` only in development via `python-dotenv`; production uses real env vars

```python
import os
api_key = os.environ["ALPHA_VANTAGE_KEY"]  # raises KeyError if not set — intentional
```

## Imports

- Use `isort` ordering: stdlib → third-party → local
- Absolute imports only (no relative `..` imports in `app/`)

## Testing

- Framework: **pytest** exclusively
- Mark all tests: `@pytest.mark.unit` or `@pytest.mark.integration`
- Mock ALL external dependencies in unit tests: yfinance, anthropic SDK, HTTP calls
- Use `pytest-asyncio` for async tests with `@pytest.mark.asyncio`
- Coverage must stay ≥ 80% (`--cov-fail-under=80`)

```python
@pytest.mark.unit
async def test_agent_stores_result(db_session, mock_yfinance):
    agent = MarketScannerAgent(db=db_session)
    await agent.run(symbol="AAPL")
    result = await db_session.get(AgentResult, ...)
    assert result is not None
```

## Security

- Run `bandit -r backend/app/` before every PR — zero high-severity findings allowed
- No `eval()`, no `exec()`, no `shell=True` in subprocess calls
- Sanitize all user-provided stock symbols before passing to external APIs (alphanumeric + `.` only)
