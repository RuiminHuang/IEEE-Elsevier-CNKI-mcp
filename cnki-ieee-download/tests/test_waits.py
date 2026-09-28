import socket
import time

import anyio
import pytest

from carsi_search import engine

pytestmark = pytest.mark.anyio


async def test_sd_cloudflare_returns_quickly(srv, sites, monkeypatch):
    monkeypatch.setattr(srv, "CHALLENGE_GRACE_SECONDS", 2)
    sites.sd_challenge = True
    t0 = time.monotonic()
    with anyio.fail_after(60):
        text = (await srv.call_tool("sciencedirect_download",
                {"url": "https://www.sciencedirect.com/science/article/pii/S0000000001"}))[0].text
    assert "ACTION_REQUIRED" in text, text
    assert time.monotonic() - t0 < 30


async def test_cnki_search_captcha_returns_quickly(srv, sites):
    sites.cnki_captcha = True
    with anyio.fail_after(40):
        text = (await srv.call_tool("cnki_search", {"query": "雷达"}))[0].text
    assert "ACTION_REQUIRED" in text, text


async def test_cdp_error_mentions_user_data_dir(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(engine, "CDP_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(engine, "_is_cdp_available", lambda: True)
    with pytest.raises(RuntimeError, match="--user-data-dir"):
        await engine.CarsiAuth().start()
