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


def _form4(code: str, day: str, shares: str = "100", price: str = "200.5") -> str:
    return f"""<?xml version="1.0"?><ownershipDocument>
<reportingOwner><reportingOwnerId>
<rptOwnerName>Doe Jane &amp; Co</rptOwnerName>
</reportingOwnerId></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction>
<transactionDate><value>{day}</value></transactionDate>
<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>{shares}</value></transactionShares>
<transactionPricePerShare><value>{price}</value></transactionPricePerShare></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""


@pytest.mark.unit
def test_form4_keeps_open_market_purchases_and_sales_only() -> None:
    from app.providers.edgar import parse_form4

    assert parse_form4(_form4("S", "2026-10-20")) == [
        {
            "Start Date": "2026-10-20",
            "Transaction": "Sale",
            "Insider": "Doe Jane & Co",
            "Shares": 100.0,
            "Value": 20050.0,
            "source": "SEC Form 4",
        }
    ]
    assert parse_form4(_form4("P", "2026-10-21"))[0]["Transaction"] == "Purchase"
    # Awards, option exercises and tax withholding are not a view on the price
    assert parse_form4(_form4("A", "2026-10-21")) == []
    assert parse_form4(_form4("M", "2026-10-21")) == []
    assert parse_form4(_form4("S", "2026-10-21", price=""))[0]["Value"] is None


@pytest.mark.unit
async def test_insider_trades_come_from_the_latest_form4_filings(make_http) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
        if "submissions/CIK0000320193" in url:
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": {
                            "form": ["4", "8-K", "4", "4"],
                            "filingDate": ["2026-10-22", "2026-10-21", "2026-10-19", "2026-06-01"],
                            "accessionNumber": ["0001-26-3", "0001-26-2", "0001-26-1", "0001-26-0"],
                            "primaryDocument": ["xslF345X06/f.xml"] * 4,
                        }
                    }
                },
            )
        # The raw XML sits beside the XSL-rendered primary document
        if url.endswith("/data/320193/0001263/f.xml"):
            return httpx.Response(200, text=_form4("S", "2026-10-20"))
        if url.endswith("/data/320193/0001261/f.xml"):
            return httpx.Response(200, text=_form4("P", "2026-10-17"))
        if url.endswith("/data/320193/0001260/f.xml"):
            return httpx.Response(200, text=_form4("P", "2026-05-29"))
        return httpx.Response(404)

    edgar = EdgarClient(make_http(handler), "agentsForStocks test@example.com")
    trades = await edgar.get_insider_transactions("AAPL")
    assert [(t["Start Date"], t["Transaction"]) for t in trades] == [
        ("2026-10-20", "Sale"),
        ("2026-10-17", "Purchase"),
        ("2026-05-29", "Purchase"),
    ]
    from datetime import date

    # Point in time: only what was filed by then
    past = await edgar.get_insider_transactions("AAPL", filed_by=date(2026, 10, 20))
    assert [t["Start Date"] for t in past] == ["2026-10-17", "2026-05-29"]
    assert await edgar.get_insider_transactions("AAPL", filings=1) == trades[:1]


@pytest.mark.unit
async def test_insider_trades_are_empty_when_sec_fails(make_http) -> None:
    edgar = EdgarClient(make_http(lambda r: httpx.Response(500)), "agentsForStocks t@example.com")
    assert await edgar.get_insider_transactions("AAPL") == []


@pytest.mark.unit
async def test_earnings_release_is_exhibit_99_1_of_the_latest_item_2_02_8k(make_http) -> None:
    from datetime import date

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
        if "submissions/CIK0000320193" in url:
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": {
                            "form": ["8-K", "8-K", "8-K"],
                            "items": ["5.02", "2.02,9.01", "2.02,9.01"],
                            "filingDate": ["2026-10-01", "2026-07-30", "2026-04-30"],
                            "accessionNumber": ["0001-26-9", "0001-26-7", "0001-26-4"],
                            "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                        }
                    }
                },
            )
        if url.endswith("/0001267/index.json"):
            names = ["b.htm", "a8-kex991q32026.htm", "ex9910.htm"]
            return httpx.Response(200, json={"directory": {"item": [{"name": n} for n in names]}})
        if url.endswith("/0001264/index.json"):
            return httpx.Response(200, json={"directory": {"item": [{"name": "ex99-1.htm"}]}})
        if url.endswith("/0001267/a8-kex991q32026.htm"):
            return httpx.Response(200, text="<p>Apple reports <b>third</b> quarter results</p>")
        if url.endswith("/0001264/ex99-1.htm"):
            return httpx.Response(200, text="<p>Second quarter</p>")
        return httpx.Response(404)

    edgar = EdgarClient(make_http(handler), "agentsForStocks test@example.com")
    assert await edgar.get_earnings_release("AAPL") == {
        "date": "2026-07-30",
        "content": "Apple reports third quarter results",
        "source": "8-K Exhibit 99.1",
    }
    earlier = await edgar.get_earnings_release("AAPL", filed_by=date(2026, 7, 29))
    assert earlier["content"] == "Second quarter"
    assert await edgar.get_earnings_release("AAPL", filed_by=date(2026, 1, 1)) == {}
    broken = EdgarClient(make_http(lambda r: httpx.Response(500)), "agentsForStocks t@e.com")
    assert await broken.get_earnings_release("AAPL") == {}
