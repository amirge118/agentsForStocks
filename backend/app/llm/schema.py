"""
Convert a Pydantic model into a JSON schema accepted by Claude structured outputs.

Structured outputs need `additionalProperties: false` and every property listed in
`required`, and do not accept numeric/string constraint keywords. Those constraints
are still enforced afterwards, when the reply is validated against the Pydantic model.
"""

from typing import Any

from pydantic import BaseModel

_UNSUPPORTED_KEYS = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "multipleOf",
    "minItems",
    "maxItems",
}


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("properties", "$defs"):
            # Maps of names → schemas: keep every name (a field may be called "title")
            cleaned[key] = {name: _clean(sub) for name, sub in value.items()}
        elif key not in _UNSUPPORTED_KEYS:
            cleaned[key] = _clean(value)
    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(cleaned["properties"])
    return cleaned


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _clean(model.model_json_schema())
