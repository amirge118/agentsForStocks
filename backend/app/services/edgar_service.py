"""
SEC EDGAR service — fetches 10-K text sections from the free SEC EDGAR REST API.
No API key required. SEC requires a non-empty User-Agent header (HTTP 403 without it).

Sections extracted:
  - Item 1  (Business)      → business model, products, competition
  - Item 1A (Risk Factors)  → regulatory, financial, operational risks

EDGAR rate limit: 10 requests/second per IP. with_retry() handles transient errors.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

import httpx

from app.services.external_api_base import with_retry
from app.services.yfinance_service import validate_symbol

logger = logging.getLogger(__name__)

_EDGAR_BASE = "https://data.sec.gov"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar"
# SEC requires a descriptive User-Agent with contact info
_HEADERS = {"User-Agent": "agentsForStocks research@agentsforstocks.com"}

# Module-level CIK cache — persists for process lifetime (tickers rarely change)
_cik_cache: dict[str, str] = {}

SectionName = Literal["business", "risk_factors"]

# Regex patterns for section extraction — tries multiple variants for robustness
_SECTION_PATTERNS: dict[SectionName, list[str]] = {
    "business": [
        r"(?si)ITEM\s+1[.\s]*BUSINESS\b.*?(?=ITEM\s+1A|ITEM\s+2\b|\Z)",
        r"(?si)Item\s+1[.\s]*Business\b.*?(?=Item\s+1A|Item\s+2\b|\Z)",
    ],
    "risk_factors": [
        r"(?si)ITEM\s+1A[.\s]*RISK\s+FACTORS\b.*?(?=ITEM\s+1B|ITEM\s+2\b|\Z)",
        r"(?si)Item\s+1A[.\s]*Risk\s+Factors\b.*?(?=Item\s+1B|Item\s+2\b|\Z)",
    ],
}

_MAX_SECTION_CHARS = 20_000


async def get_cik(symbol: str) -> str | None:
    """
    Resolve a ticker symbol to its SEC CIK number (zero-padded to 10 digits).
    Example: "AAPL" → "0000320193"
    Uses module-level cache to avoid repeated fetches within a process.
    """
    validated = validate_symbol(symbol)

    if validated in _cik_cache:
        return _cik_cache[validated]

    def _fetch() -> dict:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=_HEADERS,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = await with_retry(_fetch, label="edgar.company_tickers")
        # data is {str_int: {"cik_str": int, "ticker": str, "title": str}, ...}
        ticker_map = {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in data.values()
        }
        # Populate full cache for this process
        _cik_cache.update(ticker_map)
        return ticker_map.get(validated)
    except Exception:
        logger.warning("edgar.get_cik failed for %s", validated)
        return None


async def get_latest_10k_accession(cik: str) -> tuple[str, str] | None:
    """
    Find the most recent 10-K filing accession number and primary document name.
    Returns (accession_number_with_dashes, primary_document_filename) or None.
    Example: ("0000320193-23-000106", "0000320193-23-000106-index.htm")
    """

    def _fetch() -> dict:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{_EDGAR_BASE}/submissions/CIK{cik}.json",
                headers=_HEADERS,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = await with_retry(_fetch, label=f"edgar.submissions({cik})")
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        documents = filings.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form == "10-K":
                return accessions[i], documents[i]

        logger.warning("No 10-K found in EDGAR filings for CIK %s", cik)
        return None
    except Exception:
        logger.warning("edgar.get_latest_10k_accession failed for CIK %s", cik)
        return None


async def get_10k_section(symbol: str, section: SectionName) -> str:
    """
    Fetch and extract a specific section from the latest 10-K filing.
    Strips HTML tags and truncates to 20,000 chars.
    Returns "" if section cannot be found or fetching fails (never raises).
    """
    validated = validate_symbol(symbol)

    cik = await get_cik(validated)
    if not cik:
        logger.warning("edgar: CIK not found for %s", validated)
        return ""

    result = await get_latest_10k_accession(cik)
    if not result:
        return ""

    accession_with_dashes, primary_doc = result
    # EDGAR archive URL uses accession number without dashes for directory
    accession_no_dashes = accession_with_dashes.replace("-", "")
    doc_url = f"{_ARCHIVES_BASE}/data/{cik}/{accession_no_dashes}/{primary_doc}"

    def _fetch_doc() -> str:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(doc_url, headers=_HEADERS)
            resp.raise_for_status()
            return resp.text

    try:
        raw_html = await with_retry(_fetch_doc, label=f"edgar.10k_doc({validated})")
    except Exception:
        logger.warning("edgar: failed to fetch 10-K document for %s", validated)
        return ""

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Try each regex pattern variant until one matches
    for pattern in _SECTION_PATTERNS[section]:
        match = re.search(pattern, text)
        if match:
            extracted = match.group(0).strip()
            return extracted[:_MAX_SECTION_CHARS]

    logger.warning(
        "edgar: section %r not found in 10-K for %s — returning doc start",
        section, validated,
    )
    # Fallback: return first 20,000 chars of the stripped text
    return text[:_MAX_SECTION_CHARS]


async def get_business_section(symbol: str) -> str:
    """Extract Item 1 (Business) from the latest 10-K. Max 20,000 chars."""
    return await get_10k_section(symbol, "business")


async def get_risk_factors(symbol: str) -> str:
    """Extract Item 1A (Risk Factors) from the latest 10-K. Max 20,000 chars."""
    return await get_10k_section(symbol, "risk_factors")
