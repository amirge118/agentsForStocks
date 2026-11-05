import pytest

from app.domain.fundamentals import score_valuation


@pytest.mark.unit
def test_multiples_are_rounded_and_a_missing_one_is_na() -> None:
    detail = score_valuation({"trailingPE": None, "priceToBook": 5.615491}).detail
    assert detail == "P/E=N/A P/B=5.62 P/S=N/A"
