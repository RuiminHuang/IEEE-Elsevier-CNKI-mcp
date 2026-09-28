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


async def test_late_rendering_security_check_is_reported_as_check(srv, sites, monkeypatch):
    # live: the PDF tab showed "Security verification" but its text was not rendered yet
    monkeypatch.setattr(srv, "CHALLENGE_GRACE_SECONDS", 2)
    sites.sd_challenge = "elsevier_late"
    text = (await srv.call_tool("sciencedirect_download", {"url": ARTICLE}))[0].text
    assert "ACTION_REQUIRED" in text and "安全验证" in text, text


async def test_nearly_empty_site_page_is_not_mistaken_for_logged_out(srv, sites):
    # live: after a failed download the tool's tab sat on a blank pdfft page, and the next
    # call said "需要登录" although the user was logged in
    page, _ = await srv._ensure_page("sciencedirect")
    await page.goto(PDFFT + "&stay=1")
    text = (await srv.call_tool("sciencedirect_download", {"url": ARTICLE}))[0].text
    assert "Downloaded PDF" in text, text


async def test_clicks_the_articles_own_pdf_button(srv, sites):
    # the fake article also links a reference's PDF (SREF000001); it must not be used
    await srv.call_tool("sciencedirect_download", {"url": ARTICLE})
    assert not any("SREF000001" in u for u in sites.requests), sites.requests
