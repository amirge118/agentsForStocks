from unittest.mock import AsyncMock

import pytest

from app.pipeline.assets import FundDetector
from app.providers.errors import ProviderError


@pytest.mark.unit
async def test_detects_a_fund_from_the_info_quote_type() -> None:
    yfinance = AsyncMock()
    yfinance.get_info.side_effect = lambda s: {"quoteType": "ETF" if s == "SPY" else "EQUITY"}
    detect = FundDetector(yfinance)
    assert await detect("SPY") is True
    assert await detect("AAPL") is False


@pytest.mark.unit
async def test_a_provider_failure_counts_as_a_company(caplog) -> None:
    yfinance = AsyncMock()
    yfinance.get_info.side_effect = ProviderError("Yahoo down")
    assert await FundDetector(yfinance)("SPY") is False
    assert "running every agent" in caplog.text
