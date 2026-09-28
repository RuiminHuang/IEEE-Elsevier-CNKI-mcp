import json
import urllib.request

import pytest

pytestmark = pytest.mark.anyio
USER_URL = "https://ieeexplore.ieee.org/Xplore/home.jsp"


def _open_urls(cdp_browser) -> list[str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(cdp_browser.url + "/json/list", timeout=5) as r:
        return [t["url"] for t in json.load(r) if t.get("type") == "page"]


async def test_user_tab_is_left_alone(srv, sites):
    await srv._ensure_connection()
    user_tab = await srv._auth.context.new_page()
    await user_tab.goto(USER_URL)
    await srv.call_tool("ieee_search", {"query": "radar"})
    assert user_tab.url == USER_URL
    assert srv._pages["ieee"] is not user_tab


async def test_logout_closes_only_tool_tabs(srv, sites, cdp_browser):
    await srv._ensure_connection()
    user_tab = await srv._auth.context.new_page()
    await user_tab.goto(USER_URL)
    await srv.call_tool("cnki_detail", {"url": "https://kns.cnki.net/kcms2/article/abstract?v=A"})
    text = (await srv.call_tool("logout", {}))[0].text
    urls = _open_urls(cdp_browser)
    assert USER_URL in urls, urls
    assert not any("kcms2" in u for u in urls), urls
    assert "关闭" in text, text
