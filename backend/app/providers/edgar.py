"""
SEC EDGAR client — 10-K text sections and insider trades (Form 4) from the free
EDGAR API (no key needed, but SEC rejects requests without a descriptive
User-Agent). Limit: 10 req/s.

Sections: Item 1 (Business) and Item 1A (Risk Factors).
Every public method returns "" (or []) instead of raising — a missing 10-K is
normal for ETFs and foreign filers, and agents treat it as "no text available".

Form 4: the open-market purchases (P) and sales (S) in the issuer's latest
filings — the insider data the sentiment agent needs when Yahoo's is blocked.

Earnings release: Exhibit 99.1 of the latest 8-K under Item 2.02 (Results of
Operations) — management's own account of the quarter, free, for when FMP's
earnings-call transcripts are not in the plan.
"""

import html
import logging
import re
from datetime import date
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
# Form 4 filings read per symbol (one request each, cached for the day)
FORM4_FILINGS = 10
# Open-market trades only: awards, option exercises, tax withholding and gifts say
# nothing about what an insider thinks of the price
_FORM4_CODES = {"P": "Purchase", "S": "Sale"}
_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
# ex991.htm, ex99-1.htm, a8-kex991q3….htm, exhibit99_1.htm — but not ex9910
_EX_99_1 = re.compile(r"ex(?:hibit)?[-_]?99[-_.]?0?1(?!\d)", re.I)
MAX_RELEASE_CHARS = 8_000
_FORM4_TRANSACTION = re.compile(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", re.S)

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

    async def get_10k_section(
        self, symbol: str, section: SectionName, filed_by: date | None = None
    ) -> str:
        """The section of the latest 10-K — filed on or before `filed_by` when given."""
        ticker = validate_symbol(symbol)
        try:
            cik = await self._get_cik(ticker)
            if cik is None:
                logger.warning("edgar: CIK not found for %s", ticker)
                return ""
            filing = await self._latest_10k(cik, filed_by)
            if filing is None:
                logger.warning("edgar: no 10-K filing for %s", ticker)
                return ""
            accession, document = filing
            raw_html = await self._http.get_text(
                _ARCHIVE_URL.format(
                    # Archive paths take the CIK without its zero padding; the padded
                    # form gets an empty 301 redirect
                    cik=int(cik),
                    accession=accession.replace("-", ""),
                    document=document,
                ),
                headers=self._headers,
            )
        except ProviderError as exc:
            logger.warning("edgar: 10-K fetch failed for %s: %s", ticker, exc)
            return ""
        return extract_section(html_to_text(raw_html), section)

    async def get_insider_transactions(
        self, symbol: str, filed_by: date | None = None, filings: int = FORM4_FILINGS
    ) -> list[dict]:
        """
        Open-market purchases and sales from the latest Form 4 filings (filed on or
        before `filed_by` when given), newest first, in yfinance's row shape:
        "Start Date", "Transaction" (Purchase / Sale), "Insider", "Shares", "Value".
        """
        ticker = validate_symbol(symbol)
        try:
            cik = await self._get_cik(ticker)
            if cik is None:
                return []
            rows: list[dict] = []
            for accession, document in await self._recent(cik, "4", filed_by, filings):
                xml = await self._http.get_text(
                    _ARCHIVE_URL.format(
                        cik=int(cik),
                        accession=accession.replace("-", ""),
                        # primaryDocument is the XSL-rendered view; the raw XML sits beside it
                        document=document.rsplit("/", 1)[-1],
                    ),
                    headers=self._headers,
                )
                rows += parse_form4(xml)
        except ProviderError as exc:
            logger.warning("edgar: Form 4 fetch failed for %s: %s", ticker, exc)
            return []
        return rows

    async def get_earnings_release(self, symbol: str, filed_by: date | None = None) -> dict:
        """
        {"date", "content", "source"} of the latest earnings release (8-K Item 2.02,
        Exhibit 99.1) filed on or before `filed_by` when given; {} when there is none.
        """
        ticker = validate_symbol(symbol)
        try:
            cik = await self._get_cik(ticker)
            if cik is None:
                return {}
            for accession, _, filing_date in await self._recent_dated(
                cik, "8-K", filed_by, 3, item="2.02"
            ):
                folder = {"cik": int(cik), "accession": accession.replace("-", "")}
                index = await self._http.get_json(
                    _INDEX_URL.format(**folder), headers=self._headers
                )
                names = [i.get("name", "") for i in index.get("directory", {}).get("item", [])]
                exhibit = next(
                    (n for n in names if n.lower().endswith(".htm") and _EX_99_1.search(n)), None
                )
                if exhibit is None:
                    continue
                raw = await self._http.get_text(
                    _ARCHIVE_URL.format(**folder, document=exhibit), headers=self._headers
                )
                return {
                    "date": filing_date,
                    "content": html_to_text(raw)[:MAX_RELEASE_CHARS],
                    "source": "8-K Exhibit 99.1",
                }
        except ProviderError as exc:
            logger.warning("edgar: earnings release fetch failed for %s: %s", ticker, exc)
        return {}

    async def _get_cik(self, ticker: str) -> str | None:
        """Ticker → zero-padded 10-digit CIK. The ticker map is cached by HttpClient."""
        data = await self._http.get_json(_TICKERS_URL, headers=self._headers)
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == ticker:
                return str(entry["cik_str"]).zfill(10)
        return None

    async def _latest_10k(self, cik: str, filed_by: date | None = None) -> tuple[str, str] | None:
        """(accession number, primary document) of the most recent 10-K."""
        latest = await self._recent(cik, "10-K", filed_by, 1)
        return latest[0] if latest else None

    async def _recent(
        self, cik: str, wanted: str, filed_by: date | None, limit: int
    ) -> list[tuple[str, str]]:
        """(accession number, primary document) of the latest `limit` filings of a form."""
        return [(a, d) for a, d, _ in await self._recent_dated(cik, wanted, filed_by, limit)]

    async def _recent_dated(
        self, cik: str, wanted: str, filed_by: date | None, limit: int, item: str | None = None
    ) -> list[tuple[str, str, str | None]]:
        """
        (accession, primary document, filing date) of the latest `limit` filings of a
        form — reporting `item` (an 8-K item such as "2.02") when given.
        """
        data = await self._http.get_json(_SUBMISSIONS_URL.format(cik=cik), headers=self._headers)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        # Older payloads may lack filingDate: then no filing can be shown to be early enough
        filed = recent.get("filingDate", [None] * len(forms))
        items = recent.get("items", [""] * len(forms))
        found: list[tuple[str, str, str | None]] = []
        for form, accession, document, filing_date, reported in zip(
            forms,
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            filed,
            items,
            strict=False,
        ):
            if form != wanted or (item is not None and item not in str(reported).split(",")):
                continue
            if filed_by is not None and (
                filing_date is None or date.fromisoformat(filing_date) > filed_by
            ):
                continue
            found.append((accession, document, filing_date))
            if len(found) >= limit:
                break
        return found


def _xml_value(block: str, tag: str) -> str | None:
    """The text of <tag>…</tag>, or of <tag><value>…</value></tag>."""
    match = re.search(rf"<{tag}>\s*(?:<value>)?\s*([^<]*?)\s*(?:</value>)?\s*</{tag}>", block, re.S)
    return html.unescape(match.group(1)) if match and match.group(1) else None


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def parse_form4(xml: str) -> list[dict]:
    """Open-market purchases and sales from one Form 4 (yfinance's row shape)."""
    insider = _xml_value(xml, "rptOwnerName") or "Unknown"
    rows = []
    for block in _FORM4_TRANSACTION.findall(xml):
        kind = _FORM4_CODES.get(_xml_value(block, "transactionCode") or "")
        when = _xml_value(block, "transactionDate")
        if kind is None or when is None:
            continue
        shares = _number(_xml_value(block, "transactionShares"))
        price = _number(_xml_value(block, "transactionPricePerShare"))
        rows.append(
            {
                "Start Date": when[:10],
                "Transaction": kind,
                "Insider": insider,
                "Shares": shares,
                "Value": shares * price if shares is not None and price is not None else None,
                "source": "SEC Form 4",
            }
        )
    return rows
