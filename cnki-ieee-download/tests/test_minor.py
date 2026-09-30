from urllib.parse import urlparse

import pytest

from carsi_search import engine


def test_cdp_check_ignores_system_proxy(cdp_browser, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    assert engine._is_cdp_available() is True


@pytest.mark.anyio
async def test_cdp_connection_ignores_proxy_variables(cdp_browser, monkeypatch):
    # Playwright sends the CDP handshake through HTTP(S)_PROXY; a proxy can't reach loopback
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "")
    auth = await engine.CarsiAuth().start()
    try:
        assert auth.is_alive()
    finally:
        await auth.stop()


def test_default_cdp_url_is_localhost():
    # Edge 154 listens on the IPv6 loopback [::1] only; "localhost" reaches [::1] and 127.0.0.1
    assert urlparse(engine.DEFAULT_CDP_URL).hostname == "localhost"


@pytest.mark.anyio
async def test_localhost_reaches_a_browser_on_127_0_0_1(cdp_browser, monkeypatch):
    # like Chrome and older Edge, the test browser listens on 127.0.0.1 only
    monkeypatch.setattr(engine, "CDP_URL", cdp_browser.url.replace("127.0.0.1", "localhost"))
    auth = await engine.CarsiAuth().start()
    try:
        assert auth.is_alive()
    finally:
        await auth.stop()


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
