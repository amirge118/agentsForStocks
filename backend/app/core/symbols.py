"""Ticker symbol validation — run on every symbol before it reaches an external API."""

import re

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.]{1,10}$")


def validate_symbol(symbol: str) -> str:
    """
    Normalise and validate a ticker (alphanumeric + '.', max 10 chars).
    Raises ValueError for anything else.
    """
    clean = symbol.strip().upper()
    if not _SYMBOL_PATTERN.match(clean):
        raise ValueError(f"Invalid symbol: {symbol!r}")
    return clean
