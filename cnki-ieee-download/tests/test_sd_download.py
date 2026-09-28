import pytest

pytestmark = pytest.mark.anyio
ARTICLE = "https://www.sciencedirect.com/science/article/pii/S0000000001"
PDFFT = ARTICLE + "/pdfft?md5=0&pid=1-s2.0-S0000000001-main.pdf"


async def test_download_from_article_url_closes_pdf_tab(srv, sites):
    await srv._ensure_page("sciencedirect")
    before = len(srv._auth.context.pages)
    text = (await srv.call_tool("sciencedirect_download", {"url": ARTICLE}))[0].text
    assert "Downloaded PDF" in text, text
    assert len(srv._auth.context.pages) == before


async def test_pdfft_url_goes_through_article_page(srv, sites):
    text = (await srv.call_tool("sciencedirect_download", {"url": PDFFT, "title": "t"}))[0].text
    assert "Downloaded PDF" in text, text
    reqs = sites.requests
    first_pdfft = next(i for i, u in enumerate(reqs) if "/pdfft" in u)
    assert ARTICLE in reqs[:first_pdfft], reqs


async def test_clicks_the_articles_own_pdf_button(srv, sites):
    # the fake article also links a reference's PDF (SREF000001); it must not be used
    await srv.call_tool("sciencedirect_download", {"url": ARTICLE})
    assert not any("SREF000001" in u for u in sites.requests), sites.requests
