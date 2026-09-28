import pytest

pytestmark = pytest.mark.anyio


async def test_cnki_detail_through_fake_site(srv, sites):
    text = (await srv.call_tool("cnki_detail", {"url": "https://kns.cnki.net/kcms2/article/abstract?v=A"}))[0].text
    assert "**Paper A**" in text and "张三" in text, text


async def test_ieee_search_through_fake_site(srv, sites):
    text = (await srv.call_tool("ieee_search", {"query": "radar"}))[0].text
    assert "IEEE P1 Paper 1" in text, text
    assert any("searchresult.jsp" in u for u in sites.requests)
