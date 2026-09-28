import asyncio
import time

import pytest

pytestmark = pytest.mark.anyio

CNKI = "https://kns.cnki.net/kcms2/article/abstract?v={}"
IEEE_DOC = "https://ieeexplore.ieee.org/document/1001/"


async def _later(delay, coro):
    await asyncio.sleep(delay)
    return await coro


async def test_parallel_cnki_details_do_not_mix(srv, sites):
    await srv._ensure_page("cnki")
    sites.delays = {"v=A": 1.5}
    a, b = await asyncio.gather(
        srv.call_tool("cnki_detail", {"url": CNKI.format("A")}),
        _later(0.3, srv.call_tool("cnki_detail", {"url": CNKI.format("B")})),
    )
    assert "**Paper A**" in a[0].text and "Error" not in a[0].text, a[0].text
    assert "**Paper B**" in b[0].text and "Error" not in b[0].text, b[0].text


async def test_concurrent_first_calls_share_one_connection(srv, sites):
    await asyncio.gather(
        srv.call_tool("cnki_detail", {"url": CNKI.format("A")}),
        srv.call_tool("ieee_detail", {"url": IEEE_DOC}),
    )
    assert sites.connections == 1


async def test_different_databases_still_run_in_parallel(srv, sites):
    # Guard against over-locking: the lock is per database, not global.
    await srv.call_tool("ieee_login", {})
    await srv._ensure_page("cnki")
    sites.delays = {"v=A": 2.0, "/document/1001": 2.0}
    t0 = time.monotonic()
    a, b = await asyncio.gather(
        srv.call_tool("cnki_detail", {"url": CNKI.format("A")}),
        srv.call_tool("ieee_detail", {"url": IEEE_DOC}),
    )
    assert "**Paper A**" in a[0].text and "Abstract of 1001" in b[0].text
    assert time.monotonic() - t0 < 4.0
