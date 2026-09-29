import pytest
from playwright.async_api import Page

pytestmark = pytest.mark.anyio
ARTICLE = "https://www.sciencedirect.com/science/article/pii/S0000000001"


@pytest.fixture
def fronted(monkeypatch):
    """URLs of the tabs brought to the front. Headless Chromium reports every tab as visible
    and focused, so the call is the only observable; the real bring_to_front still runs."""
    urls = []
    real = Page.bring_to_front

    async def spy(self):
        urls.append(self.url)
        return await real(self)

    monkeypatch.setattr(Page, "bring_to_front", spy)
    return urls


@pytest.mark.parametrize("challenge", ["elsevier", "cloudflare"])
async def test_sd_download_check_is_brought_to_front(srv, sites, fronted, monkeypatch, challenge):
    monkeypatch.setattr(srv, "CHALLENGE_GRACE_SECONDS", 1)
    sites.sd_challenge = challenge
    text = (await srv.call_tool("sciencedirect_download", {"url": ARTICLE}))[0].text
    assert "ACTION_REQUIRED" in text and "最前面" in text, text
    assert fronted and "pdf.sciencedirectassets.com" in fronted[-1], fronted


async def test_sd_search_check_is_brought_to_front(srv, sites, fronted):
    sites.sd_search_challenge = True
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar"}))[0].text
    assert "ACTION_REQUIRED" in text and "最前面" in text, text
    assert fronted and "www.sciencedirect.com/search" in fronted[-1], fronted


async def test_cnki_captcha_is_brought_to_front(srv, sites, fronted):
    sites.cnki_captcha = True
    text = (await srv.call_tool("cnki_search", {"query": "雷达"}))[0].text
    assert "ACTION_REQUIRED" in text and "最前面" in text, text
    assert fronted and "kns.cnki.net" in fronted[-1], fronted


async def test_ieee_pdf_check_is_opened_and_brought_to_front(srv, sites, fronted):
    # the check came back from an in-page fetch, so it is opened in the tab to be completed there
    sites.ieee_pdf_challenge = True
    text = (await srv.call_tool("ieee_download", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
    assert "ACTION_REQUIRED" in text and "最前面" in text, text
    assert fronted and "ieeexplore.ieee.org/stamp" in fronted[-1], fronted


async def test_successful_download_does_not_steal_focus(srv, sites, fronted):
    text = (await srv.call_tool("sciencedirect_download", {"url": ARTICLE}))[0].text
    assert "Downloaded PDF" in text, text
    assert fronted == []
