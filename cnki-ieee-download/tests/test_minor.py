import pytest

from carsi_search import engine


def test_cdp_check_ignores_system_proxy(cdp_browser, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    assert engine._is_cdp_available() is True


@pytest.mark.anyio
async def test_cnki_far_page(srv, sites):
    sites.cnki_total_pages, sites.cnki_delay_ms = 60, 100
    text = (await srv.call_tool("cnki_search", {"query": "雷达", "page": 55}))[0].text
    assert "P55R1" in text and "55/60" in text, text


@pytest.mark.anyio
async def test_cnki_labels(srv, sites):
    text = (await srv.call_tool("cnki_search", {"query": "雷达"}))[0].text
    assert "来源: " in text and "期刊: " not in text, text
    detail = (await srv.call_tool("cnki_detail", {"url": "https://kns.cnki.net/kcms2/article/abstract?v=A"}))[0].text
    assert "**来源**: 测试期刊\n" in detail, detail
