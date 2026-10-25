"""
Logging setup. Every `logger.x(..., extra={...})` field (symbol, run_id, error, …)
is included in the output — the plain stdlib format silently drops them.

LOG_FORMAT=text  → `... ERROR app.agents.runner Agent run failed agent=moat symbol=AAPL …`
LOG_FORMAT=json  → one JSON object per line, for log aggregation in production.
Values of sensitive keys (api_key, token, password, …) are redacted.

Every record also carries the current run context (pipeline_run_id, run_id, agent,
symbol — app/core/context.py), so all lines of one run can be filtered together,
including those from providers and the LLM client. uvicorn's own loggers are
routed through the same handler, so access logs are JSON too.
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from app.core.context import current_fields

# Attributes every LogRecord has — anything else on a record came from `extra=`
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn's ANSI-coloured duplicate of the message
}
_SENSITIVE = ("password", "token", "secret", "api_key", "apikey", "authorization")
REDACTED = "***"

# Secrets that travel in URLs (FMP sends `?apikey=`) — scrubbed from every message
_SECRET_IN_TEXT = re.compile(r"(?i)\b(api_?key|token|secret|password|authorization)=([^&\s\"']+)")
# Libraries that log full request URLs at INFO
_QUIET_LOGGERS = ("httpx", "httpcore", "httpx2", "httpcore2", "urllib3")
# uvicorn installs its own handlers; ours replace them so its lines share our format
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def scrub(text: str) -> str:
    return _SECRET_IN_TEXT.sub(lambda m: f"{m.group(1)}={REDACTED}", text)


def _is_sensitive(key: str) -> bool:
    """
    Whole-word match, so `api_key` / `access_token` / `password_hash` are redacted
    but counters such as `input_tokens` are not.
    """
    name = key.lower()
    parts = name.split("_")
    return any(
        name == word or name.endswith(f"_{word}") or name.startswith(f"{word}_") or word in parts
        for word in _SENSITIVE
    )


def extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """The record's `extra=` fields (and run context), with sensitive values redacted."""
    return _extras(record)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    fields = {}
    for key, value in vars(record).items():
        if key in _STANDARD_ATTRS or key.startswith("_"):
            continue
        fields[key] = REDACTED if _is_sensitive(key) else value
    return fields


class ContextFilter(logging.Filter):
    """
    Adds the current run context to each record (explicit `extra=` values win),
    and the active trace / span ids, so a log line links to its trace.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_fields().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        span = trace.get_current_span().get_span_context()
        if span.is_valid and not hasattr(record, "trace_id"):
            record.trace_id = format(span.trace_id, "032x")
            record.span_id = format(span.span_id, "016x")
        return True


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extras(record)
        if extras:
            line += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return scrub(line)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return scrub(json.dumps(payload, default=str))


_HANDLER_MARK = "_agents_for_stocks_handler"


def configure_logging(fmt: str = "text", level: str = "INFO") -> None:
    """
    Install our stdout handler on the root logger. Idempotent: replaces only a
    handler installed by an earlier call, never other handlers (e.g. pytest's).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    setattr(handler, _HANDLER_MARK, True)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
