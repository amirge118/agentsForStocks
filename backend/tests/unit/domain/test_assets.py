import pytest

from app.domain.assets import is_fund


@pytest.mark.unit
@pytest.mark.parametrize(
    ("info", "fund"),
    [
        ({"quoteType": "ETF"}, True),
        ({"quoteType": "mutualfund"}, True),
        ({"quoteType": "EQUITY"}, False),
        ({}, False),  # unknown → treated as a company, every agent runs
        ({"quoteType": None}, False),
    ],
)
def test_is_fund(info: dict, fund: bool) -> None:
    assert is_fund(info) is fund
