from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMClient
from app.llm.errors import QuotaExhaustedError
from app.llm.pricing import Price
from app.llm.spend import DailySpend, is_paid
from app.repositories.llm_calls import LLMCallRepository
from app.schemas.signals import LLMSignal

DAY = date(2026, 10, 28)
REPLY = '{"signal": "bullish", "confidence": 70, "reasoning": "r"}'


@pytest.mark.unit
def test_free_models_are_not_paid_and_unknown_ones_are() -> None:
    assert not is_paid(Price.flat(0, 0))
    assert is_paid(Price.flat(1.0, 5.0))
    assert is_paid(None)


@pytest.mark.unit
async def test_the_cap_refuses_once_spent_and_resets_the_next_day(caplog) -> None:
    today = [DAY]
    spend = DailySpend(1.0, today=lambda: today[0])
    await spend.check("anthropic", "m")
    spend.add(0.85)
    assert "Daily LLM budget at 85%" in caplog.text
    await spend.check("anthropic", "m")
    spend.add(0.2)
    with pytest.raises(QuotaExhaustedError, match=r"\$1.00 spent"):
        await spend.check("anthropic", "m")
    with pytest.raises(QuotaExhaustedError):
        await spend.check("anthropic", "m")
    assert caplog.text.count("Daily LLM budget spent") == 1  # one alert a day, not per call

    today[0] = date(2026, 10, 29)
    await spend.check("anthropic", "m")
    assert spend.spent == 0.0


@pytest.mark.unit
async def test_the_days_spend_is_seeded_from_the_ledger() -> None:
    seen: list[datetime] = []

    async def load(since: datetime) -> float:
        seen.append(since)
        return 5.0

    spend = DailySpend(5.0, load, today=lambda: DAY)
    with pytest.raises(QuotaExhaustedError):
        await spend.check("anthropic", "m")
    assert seen[0].date() == DAY and seen[0].hour == 0  # midnight in New York
    assert str(seen[0].tzinfo) == "America/New_York"


@pytest.mark.unit
async def test_no_cap_and_a_failing_ledger_never_block() -> None:
    await DailySpend(0).check("anthropic", "m")

    async def broken(since: datetime) -> float:
        raise RuntimeError("db down")

    await DailySpend(1.0, broken, today=lambda: DAY).check("anthropic", "m")


@pytest.mark.unit
async def test_claude_is_not_called_once_the_budget_is_spent() -> None:
    message = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=REPLY)],
        usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0),
    )
    sdk = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))
    price = {"m": Price.flat(1.0, 5.0)}  # $1 per million input tokens
    spend = DailySpend(1.0, today=lambda: DAY)
    client = LLMClient(sdk, default_model="m", prices=price, spend=spend)

    await client.generate(system="s", prompt="p", schema=LLMSignal)
    assert spend.spent == pytest.approx(1.0)  # the recorded call's cost was added
    with pytest.raises(QuotaExhaustedError):
        await client.generate(system="s", prompt="p", schema=LLMSignal)
    assert sdk.messages.create.await_count == 1


@pytest.mark.unit
async def test_cost_since_sums_the_ledger(db_session) -> None:
    from app.models.llm_call import LLMCall

    def call(at: datetime, cost: float | None) -> LLMCall:
        return LLMCall(
            call_id=str(at) + str(cost),
            created_at=at,
            model="m",
            prompt_version="v",
            status="ok",
            latency_ms=1,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=cost,
        )

    db_session.add_all(
        [
            call(datetime(2026, 10, 27, 12), 3.0),
            call(datetime(2026, 10, 28, 12), 0.25),
            call(datetime(2026, 10, 28, 13), None),
            call(datetime(2026, 10, 28, 14), 0.5),
        ]
    )
    await db_session.flush()
    assert await LLMCallRepository(db_session).cost_since(datetime(2026, 10, 28)) == 0.75
