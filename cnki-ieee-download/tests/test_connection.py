import asyncio
import time

import pytest

pytestmark = pytest.mark.anyio

CNKI = "https://kns.cnki.net/kcms2/article/abstract?v={}"


async def _wait_disconnected(auth, timeout=10):
    deadline = time.time() + timeout
    while auth.browser.is_connected() and time.time() < deadline:
        await asyncio.sleep(0.2)


async def test_closed_tab_is_replaced(srv, sites):
    await srv.call_tool("cnki_detail", {"url": CNKI.format("A")})
    await srv._pages["cnki"].close()
    text = (await srv.call_tool("cnki_detail", {"url": CNKI.format("B")}))[0].text
    assert "**Paper B**" in text, text


async def test_cnki_reconnects_after_browser_closed(srv, sites, cdp_browser):
    await srv.call_tool("cnki_detail", {"url": CNKI.format("A")})
    old = srv._auth
    cdp_browser.kill()
    await _wait_disconnected(old)
    text = (await srv.call_tool("cnki_detail", {"url": CNKI.format("B")}))[0].text
    assert "**Paper B**" in text, text
    assert srv._auth is not old and srv._auth.is_alive()


async def test_ieee_reconnects_after_browser_closed(srv, sites, cdp_browser):
    await srv.call_tool("ieee_detail", {"url": "https://ieeexplore.ieee.org/document/1001/"})
    old = srv._auth
    cdp_browser.kill()
    await _wait_disconnected(old)
    text = (await srv.call_tool("ieee_detail", {"url": "https://ieeexplore.ieee.org/document/1002/"}))[0].text
    assert "Abstract of 1002" in text, text


async def test_status_after_browser_closed(srv, sites, cdp_browser):
    await srv.call_tool("cnki_detail", {"url": CNKI.format("A")})
    old = srv._auth
    cdp_browser.kill()
    await _wait_disconnected(old)
    text = (await srv.call_tool("status", {}))[0].text
    assert "未连接" in text, text


async def test_logout_keeps_browser_running(srv, sites, cdp_browser):
    cdp_browser.kill()   # let CarsiAuth launch the browser itself, as in production
    await srv.call_tool("cnki_detail", {"url": CNKI.format("A")})
    assert srv._auth._browser_process is not None
    text = (await srv.call_tool("logout", {}))[0].text
    assert "已断开" in text
    await asyncio.sleep(2)   # a terminated process needs a moment before poll() reports it
    assert cdp_browser.running()
