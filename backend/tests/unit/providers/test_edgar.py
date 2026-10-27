import httpx
import pytest

from app.providers.edgar import EdgarClient, extract_section, html_to_text

_DOC = """
<html><body>
<p>Table of contents: Item 1. Business ... Item 1A. Risk Factors ...</p>
<h2>Item 1. Business</h2><p>We design phones &amp; computers with a large installed base.</p>
<h2>Item 1A. Risk Factors</h2><p>Customer concentration&#8217;s risk and litigation.</p>
<h2>Item 1B. Unresolved Staff Comments</h2><p>None.</p>
<h2>Item 2. Properties</h2>
</body></html>
"""


def _edgar_handler(request: httpx.Request) -> httpx.Response:
    assert "agentsForStocks" in request.headers["User-Agent"]
    url = str(request.url)
    if url.endswith("company_tickers.json"):
        return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
    if "submissions/CIK0000320193" in url:
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "form": ["8-K", "10-K"],
                        "accessionNumber": ["0000320193-26-000001", "0000320193-25-000106"],
                        "primaryDocument": ["a.htm", "aapl-10k.htm"],
                    }
                }
            },
        )
    if url.endswith("/data/320193/000032019325000106/aapl-10k.htm"):
        return httpx.Response(200, text=_DOC)
    if url.endswith("/data/0000320193/000032019325000106/aapl-10k.htm"):
        # What SEC really does with a zero-padded CIK in an archive URL: an empty redirect
        return httpx.Response(301, headers={"Location": url.replace("/0000320193/", "/320193/")})
    return httpx.Response(404)


@pytest.mark.unit
def test_html_to_text_decodes_entities() -> None:
    assert html_to_text("<p>A&amp;B&nbsp; &#8217;s</p>") == "A&B ’s"


@pytest.mark.unit
def test_extract_section_skips_table_of_contents() -> None:
    text = html_to_text(_DOC)
    business = extract_section(text, "business")
    assert "installed base" in business
    assert "Customer concentration" not in business
    risks = extract_section(text, "risk_factors")
    assert "litigation" in risks
    assert "Unresolved" not in risks


@pytest.mark.unit
def test_extract_section_falls_back_to_document_start() -> None:
    assert extract_section("no headings here", "business") == "no headings here"


@pytest.mark.unit
async def test_full_flow_fetches_latest_10k(make_http) -> None:
    edgar = EdgarClient(make_http(_edgar_handler), user_agent="agentsForStocks test@example.com")
    assert "installed base" in await edgar.get_business_section("AAPL")
    assert "litigation" in await edgar.get_risk_factors("AAPL")


@pytest.mark.unit
async def test_unknown_ticker_or_failures_return_empty_string(make_http) -> None:
    edgar = EdgarClient(make_http(_edgar_handler), user_agent="agentsForStocks test@example.com")
    assert await edgar.get_business_section("ZZZZ") == ""

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    edgar = EdgarClient(make_http(broken), user_agent="agentsForStocks test@example.com")
    assert await edgar.get_risk_factors("AAPL") == ""


@pytest.mark.unit
async def test_company_without_10k_returns_empty(make_http) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "SPY"}})
        return httpx.Response(200, json={"filings": {"recent": {"form": ["N-CSR"]}}})

    edgar = EdgarClient(make_http(handler), user_agent="agentsForStocks test@example.com")
    assert await edgar.get_business_section("SPY") == ""


def _two_10ks(with_dates: bool = True):
    recent = {
        "form": ["10-K", "8-K", "10-K"],
        "accessionNumber": ["0000320193-25-000106", "0000320193-25-000050", "0000320193-24-000123"],
        "primaryDocument": ["new.htm", "x.htm", "old.htm"],
    }
    if with_dates:
        recent["filingDate"] = ["2025-10-31", "2025-05-01", "2024-11-01"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
        if "submissions/" in url:
            return httpx.Response(200, json={"filings": {"recent": recent}})
        year = "2025" if url.endswith("new.htm") else "2024"
        body = f"<p>Item 1. Business</p><p>Fiscal {year} filing about the installed base.</p>"
        return httpx.Response(200, text=body + "<p>Item 1A. Risk Factors</p><p>Risks.</p>")

    return handler


@pytest.mark.unit
async def test_10k_filed_by_a_date_picks_the_one_known_then(make_http) -> None:
    from datetime import date

    edgar = EdgarClient(make_http(_two_10ks()), user_agent="agentsForStocks test@example.com")
    assert "2025" in await edgar.get_10k_section("AAPL", "business")
    assert "2024" in await edgar.get_10k_section("AAPL", "business", filed_by=date(2025, 6, 1))
    assert "2025" in await edgar.get_10k_section("AAPL", "business", filed_by=date(2025, 10, 31))
    assert await edgar.get_10k_section("AAPL", "business", filed_by=date(2024, 1, 1)) == ""

    undated = EdgarClient(
        make_http(_two_10ks(with_dates=False)), user_agent="agentsForStocks test@example.com"
    )
    assert "2025" in await undated.get_10k_section("AAPL", "business")
    # No filing date: none can be shown to have been filed early enough
    assert await undated.get_10k_section("AAPL", "business", filed_by=date(2025, 6, 1)) == ""
