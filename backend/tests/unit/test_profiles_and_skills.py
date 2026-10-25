import json

import pytest

from app.llm.profiles import AgentProfile, ProfileBook
from app.llm.skills import available_skills, compose_system, load_skill, prompt_label


@pytest.mark.unit
def test_skills_have_front_matter_and_compose_in_order() -> None:
    names = {s.name for s in available_skills()}
    assert {"confidence_calibration", "valuation_judgement", "moat_evidence"} <= names
    skill = load_skill("confidence_calibration")
    assert skill.version == "1" and skill.description and "Never exceed 95" in skill.body

    system = compose_system("valuation", ("valuation_judgement", "confidence_calibration"))
    assert system.startswith("You are a quantitative valuation analyst")
    assert system.index("Valuation judgement") < system.index("Confidence calibration")
    assert prompt_label("valuation", ()) == "valuation"
    assert prompt_label("valuation", ("a", "b")) == "valuation+a+b"


@pytest.mark.unit
def test_unknown_skill_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown skill 'nope'.*confidence_calibration"):
        load_skill("nope")


@pytest.mark.unit
def test_profile_resolution_precedence(tmp_path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"*": {"provider": "alt"}, "moat": {"model": "m1"}}))
    book = ProfileBook.from_config(
        inline='{"moat": {"skills": ["moat_evidence"]}, "news_sentiment": {"use_llm": false}}',
        path=str(path),
    )
    default = AgentProfile(max_tokens=512)
    moat = book.resolve("moat", default)
    # file "moat" entry is replaced by the inline one (inline wins per key)
    assert (moat.provider, moat.model, moat.skills, moat.max_tokens) == (
        "alt",
        None,
        ("moat_evidence",),
        512,
    )
    assert book.resolve("news_sentiment", default).use_llm is False
    assert book.resolve("risk", default).provider == "alt"  # "*" applies everywhere
    assert ProfileBook().resolve("risk", default) == default


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [{"moat": {"modle": "typo"}}, {"moat": {"skills": ["does_not_exist"]}}],
)
def test_bad_overrides_fail_at_startup(overrides) -> None:
    with pytest.raises(ValueError):
        ProfileBook(overrides)
