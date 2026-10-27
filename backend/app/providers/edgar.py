"""
SEC EDGAR client — 10-K text sections from the free EDGAR API (no key needed,
but SEC rejects requests without a descriptive User-Agent). Limit: 10 req/s.

Sections: Item 1 (Business) and Item 1A (Risk Factors).
Every public method returns "" instead of raising — a missing 10-K is normal
for ETFs and foreign filers, and agents treat it as "no text available".
"""

import html
import logging
import re
from typing import Literal

from app.core.symbols import validate_symbol
from app.providers.errors import ProviderError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

SectionName = Literal["business", "risk_factors"]

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
MAX_SECTION_CHARS = 20_000

# Section start → the heading that ends it. Case-insensitive; the 10-K table of
# contents also matches, so the longest match wins (the body, not the TOC line).
_SECTION_PATTERNS: dict[SectionName, re.Pattern[str]] = {
    "business": re.compile(
        r"item\s*1\s*[.:\-—]?\s*business\b.*?(?=item\s*1a\b|item\s*2\b|\Z)", re.I | re.S
    ),
    "risk_factors": re.compile(
        r"item\s*1a\s*[.:\-—]?\s*risk\s+factors\b.*?(?=item\s*1b\b|item\s*2\b|\Z)", re.I | re.S
    ),
}


def html_to_text(raw_html: str) -> str:
    """Strip tags, decode entities (&nbsp; &#8217; …) and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_section(text: str, section: SectionName) -> str:
    """Return the requested 10-K section, or the start of the document if it can't be found."""
    matches = _SECTION_PATTERNS[section].findall(text)
    if matches:
        return max(matches, key=len).strip()[:MAX_SECTION_CHARS]
    logger.warning("edgar: section %r not found — returning document start", section)
    return text[:MAX_SECTION_CHARS]


class EdgarClient:
    def __init__(self, http: HttpClient, user_agent: str) -> None:
        self._http = http
        self._headers = {"User-Agent": user_agent}

    async def get_business_section(self, symbol: str) -> str:
        return await self.get_10k_section(symbol, "business")

    async def get_risk_factors(self, symbol: str) -> str:
        return await self.get_10k_section(symbol, "risk_factors")

    async def get_10k_section(self, symbol: str, section: SectionName) -> str:
        ticker = validate_symbol(symbol)
        try:
            cik = await self._get_cik(ticker)
            if cik is None:
                logger.warning("edgar: CIK not found for %s", ticker)
                return ""
            filing = await self._latest_10k(cik)
            if filing is None:
                logger.warning("edgar: no 10-K filing for %s", ticker)
                return ""
            accession, document = filing
            raw_html = await self._http.get_text(
                # The archive path takes the CIK without zero padding: the padded form
                # answers with a 301 redirect and an empty body
                _ARCHIVE_URL.format(
                    cik=int(cik), accession=accession.replace("-", ""), document=document
                ),
                headers=self._headers,
            )
        except ProviderError as exc:
            logger.warning("edgar: 10-K fetch failed for %s: %s", ticker, exc)
            return ""
        return extract_section(html_to_text(raw_html), section)

    async def _get_cik(self, ticker: str) -> str | None:
        """Ticker → zero-padded 10-digit CIK. The ticker map is cached by HttpClient."""
        data = await self._http.get_json(_TICKERS_URL, headers=self._headers)
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == ticker:
                return str(entry["cik_str"]).zfill(10)
        return None

    async def _latest_10k(self, cik: str) -> tuple[str, str] | None:
        """(accession number, primary document) of the most recent 10-K."""
        data = await self._http.get_json(_SUBMISSIONS_URL.format(cik=cik), headers=self._headers)
        recent = data.get("filings", {}).get("recent", {})
        for form, accession, document in zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            strict=False,
        ):
            if form == "10-K":
                return accession, document
        return None
