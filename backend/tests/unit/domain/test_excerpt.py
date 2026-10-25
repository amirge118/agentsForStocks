import pytest

from app.domain.financials import HIGH_RISK_KEYWORDS, MOAT_KEYWORDS
from app.domain.stats import relevant_excerpt

BOILERPLATE = "We design, manufacture and market products and services in many markets. "


def _ten_k(chars: int, buried: list[str]) -> str:
    """A long Business / Risk section with the sentences that matter buried deep inside."""
    filler = BOILERPLATE * (chars // len(BOILERPLATE))
    third = len(filler) // 3
    return (
        filler[:third]
        + " ".join(buried[: len(buried) // 2])
        + " "
        + filler[third : 2 * third]
        + " ".join(buried[len(buried) // 2 :])
        + " "
        + filler[2 * third :]
    )


@pytest.mark.unit
def test_short_text_is_returned_unchanged() -> None:
    assert relevant_excerpt("Short. Text.", MOAT_KEYWORDS, 100) == "Short. Text."


@pytest.mark.unit
def test_keeps_the_opening_and_the_buried_keyword_sentences_within_budget() -> None:
    buried = [
        "Our patent portfolio covers the core display technology.",
        "Customers face high switching costs once integrated.",
        "The installed base exceeds two billion devices.",
    ]
    text = _ten_k(30_000, buried)
    excerpt = relevant_excerpt(text, MOAT_KEYWORDS, 3_500)
    assert len(excerpt) <= 3_500
    assert excerpt.startswith("We design")  # context first
    for sentence in buried:
        assert sentence in excerpt
    assert "…" in excerpt  # gaps are marked
    # The old cut — the first 3,500 characters — would have kept none of them
    assert not any(sentence in text[:3_500] for sentence in buried)


@pytest.mark.unit
def test_no_keyword_falls_back_to_the_beginning() -> None:
    text = BOILERPLATE * 200
    assert relevant_excerpt(text, HIGH_RISK_KEYWORDS, 1_000) == text[:1_000]


@pytest.mark.unit
def test_new_budgets_cut_the_10k_tokens_and_keep_the_risk_evidence() -> None:
    risks = [
        "There is substantial doubt about our ability to continue as a going concern.",
        "We identified a material weakness in internal control over financial reporting.",
        "Customer concentration: one customer accounts for 41% of revenue.",
    ]
    text = _ten_k(40_000, risks)
    old = text[:8_000]
    new = relevant_excerpt(text, HIGH_RISK_KEYWORDS, 4_500)
    assert len(new) <= len(old) * 0.6  # ≥ 40% fewer characters (≈ tokens)
    assert sum(r in new for r in risks) == 3 and sum(r in old for r in risks) == 0
