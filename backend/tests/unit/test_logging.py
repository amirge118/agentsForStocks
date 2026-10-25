import json
import logging

import pytest

from app.core.logging import REDACTED, JsonFormatter, TextFormatter, configure_logging, scrub


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        "app.agents.runner", logging.ERROR, __file__, 1, "Agent run failed", (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.mark.unit
def test_text_format_appends_extra_fields() -> None:
    """Regression: the plain stdlib format dropped symbol / run_id / error."""
    line = TextFormatter().format(
        _record(agent="moat", symbol="AAPL", run_id="r-1", error="HTTP 403")
    )
    assert line.endswith(
        "ERROR app.agents.runner Agent run failed agent=moat symbol=AAPL run_id=r-1 error=HTTP 403"
    )


@pytest.mark.unit
def test_text_format_without_extras_is_unchanged() -> None:
    assert TextFormatter().format(_record()).endswith("app.agents.runner Agent run failed")


@pytest.mark.unit
def test_json_format_is_one_parseable_object() -> None:
    payload = json.loads(JsonFormatter().format(_record(symbol="AAPL", counts={"failed": 1})))
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "app.agents.runner"
    assert payload["message"] == "Agent run failed"
    assert payload["symbol"] == "AAPL"
    assert payload["counts"] == {"failed": 1}
    assert payload["ts"].endswith("+00:00")


@pytest.mark.unit
def test_json_format_includes_exceptions_and_unserialisable_values() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = _record(when=object())
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in payload["exc_info"]
    assert payload["when"].startswith("<object")


@pytest.mark.unit
@pytest.mark.parametrize(
    "key", ["api_key", "authorization", "openviking_api_key", "TOKEN", "password"]
)
def test_sensitive_extras_are_redacted(key: str) -> None:
    record = _record(**{key: "s3cret"})
    assert "s3cret" not in TextFormatter().format(record)
    assert json.loads(JsonFormatter().format(record))[key] == REDACTED


@pytest.mark.unit
def test_configure_logging_is_idempotent_and_keeps_foreign_handlers() -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    saved_level = root.level
    try:
        configure_logging("json", "warning")
        configure_logging("text", "debug")
        ours = [h for h in root.handlers if getattr(h, "_agents_for_stocks_handler", False)]
        assert len(ours) == 1
        assert isinstance(ours[0].formatter, TextFormatter)
        assert foreign in root.handlers
        assert root.level == logging.DEBUG
    finally:
        root.removeHandler(foreign)
        for h in [h for h in root.handlers if getattr(h, "_agents_for_stocks_handler", False)]:
            root.removeHandler(h)
        root.setLevel(saved_level)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "GET https://fmp/api/v3/profile/AAPL?limit=5&apikey=abc123 200",
            "GET https://fmp/api/v3/profile/AAPL?limit=5&apikey=*** 200",
        ),
        ("token=xyz password=hunter2", "token=*** password=***"),
        ("API_KEY=k1&x=1", "API_KEY=***&x=1"),
        ("symbol=AAPL limit=5", "symbol=AAPL limit=5"),
    ],
)
def test_scrub_removes_secrets_from_urls_and_text(text: str, expected: str) -> None:
    assert scrub(text) == expected


@pytest.mark.unit
def test_formatted_messages_never_contain_url_secrets() -> None:
    """Regression: httpx logged FMP request URLs including ?apikey=<key> at INFO."""
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: GET %s",
        ("https://x/y?apikey=LEAK",),
        None,
    )
    assert "LEAK" not in TextFormatter().format(record)
    assert "LEAK" not in JsonFormatter().format(record)


@pytest.mark.unit
def test_configure_logging_quiets_url_logging_libraries() -> None:
    root = logging.getLogger()
    saved = root.level
    try:
        configure_logging("text", "info")
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        for h in [h for h in root.handlers if getattr(h, "_agents_for_stocks_handler", False)]:
            root.removeHandler(h)
        root.setLevel(saved)
