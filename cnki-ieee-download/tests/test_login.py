import pytest

import server

LONG = " filler" * 30


@pytest.mark.parametrize("url,expected", [
    ("https://ieeexplore.ieee.org/search/searchresult.jsp?queryText=load%20forecasting", False),
    ("https://www.sciencedirect.com/search?qs=broadcast%20cascade", False),
    ("https://kns.cnki.net/kns8s/search", False),
    ("https://www.sciencedirect.com/journal/journal-of-the-association", False),
    ("https://ieeexplore.ieee.org/document/123/", False),
    ("https://ieeexplore.ieee.org/servlet/wayf.jsp?entityId=x", True),
    ("https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=x", True),
    ("https://idp.xidian.edu.cn/idp/profile/SAML2/Redirect/SSO", True),
    ("https://ids.xidian.edu.cn/authserver/login?service=x", True),
    ("https://fsso.cnki.net/", True),
    ("https://login.cnki.net/login/", True),
])
def test_is_login_url(url, expected):
    assert server._is_login_url(url) is expected


@pytest.mark.parametrize("db,text,expected", [
    ("ieee", "", False),
    ("ieee", "Loading...", False),
    ("ieee", "Institutional Sign In" + LONG, False),
    ("ieee", "Access provided by: Test University" + LONG, True),
    ("sciencedirect", "Just a moment..." + LONG, False),
    ("cnki", "机构登录 校外访问" + LONG, False),
    ("cnki", "Test University 欢迎您 退出" + LONG, True),
])
def test_is_logged_in(db, text, expected):
    assert server._is_logged_in(db, text) is expected


@pytest.mark.anyio
async def test_ieee_search_works_without_login(srv, sites):
    sites.logged_in["ieee"] = False
    text = (await srv.call_tool("ieee_search", {"query": "radar"}))[0].text
    assert "IEEE P1 Paper 1" in text, text


@pytest.mark.anyio
async def test_sd_detail_works_without_login(srv, sites):
    sites.logged_in["sciencedirect"] = False
    url = "https://www.sciencedirect.com/science/article/pii/S0000000001"
    text = (await srv.call_tool("sciencedirect_detail", {"url": url}))[0].text
    assert "Summary of S0000000001" in text, text


@pytest.mark.anyio
async def test_ieee_download_still_requires_login(srv, sites):
    sites.logged_in["ieee"] = False
    text = (await srv.call_tool("ieee_download", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
    assert "需要登录" in text, text


@pytest.mark.anyio
async def test_login_ok_after_searching_forecasting(srv, sites):
    await srv.call_tool("ieee_search", {"query": "load forecasting"})
    text = (await srv.call_tool("ieee_login", {}))[0].text
    assert "✅" in text, text


@pytest.mark.anyio
async def test_check_login_on_closed_page_is_not_success(srv, sites):
    page, _ = await srv._ensure_page("ieee")
    await page.close()
    assert await srv._check_login("ieee", page) == "login"


@pytest.mark.anyio
async def test_status_does_not_claim_login(srv, sites):
    sites.logged_in["cnki"] = False
    await srv.call_tool("cnki_detail", {"url": "https://kns.cnki.net/kcms2/article/abstract?v=A"})
    text = (await srv.call_tool("status", {}))[0].text
    assert "logged in" not in text, text
