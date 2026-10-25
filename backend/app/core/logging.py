"""
Logging setup. Every `logger.x(..., extra={...})` field (symbol, run_id, error, …)
is included in the output — the plain stdlib format silently drops them.

LOG_FORMAT=text  → `... ERROR app.agents.runner Agent run failed agent=moat symbol=AAPL …`
LOG_FORMAT=json  → one JSON object per line, for log aggregation in production.
Values of sensitive keys (api_key, token, password, …) are redacted.
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord has — anything else on a record came from `extra=`
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
}
_SENSITIVE = ("password", "token", "secret", "api_key", "apikey", "authorization")
REDACTED = "***"

# Secrets that travel in URLs (FMP sends `?apikey=`) — scrubbed from every message
_SECRET_IN_TEXT = re.compile(r"(?i)\b(api_?key|token|secret|password|authorization)=([^&\s\"']+)")
# Libraries that log full request URLs at INFO
_QUIET_LOGGERS = ("httpx", "httpcore", "urllib3")


def scrub(text: str) -> str:
    return _SECRET_IN_TEXT.sub(lambda m: f"{m.group(1)}={REDACTED}", text)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    fields = {}
    for key, value in vars(record).items():
        if key in _STANDARD_ATTRS or key.startswith("_"):
            continue
        sensitive = any(word in key.lower() for word in _SENSITIVE)
        fields[key] = REDACTED if sensitive else value
    return fields


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
    setattr(handler, _HANDLER_MARK, True)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
