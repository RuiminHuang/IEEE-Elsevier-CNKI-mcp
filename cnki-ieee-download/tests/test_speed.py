import time
from pathlib import Path

import pytest

import fake_sites

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("tool,args", [
    ("ieee_detail", {"url": "https://ieeexplore.ieee.org/document/1001/"}),
    ("ieee_search", {"query": "radar"}),
    ("sciencedirect_search", {"query": "radar"}),
    ("sciencedirect_detail", {"url": "https://www.sciencedirect.com/science/article/pii/S0000000001"}),
    ("cnki_detail", {"url": "https://kns.cnki.net/kcms2/article/abstract?v=A"}),
])
async def test_busy_pages_do_not_wait_for_network_idle(srv, sites, tool, args):
    await srv._ensure_page(tool.split("_")[0])     # exclude connection setup from the timing
    sites.busy_network = True
    t0 = time.monotonic()
    text = (await srv.call_tool(tool, args))[0].text
    elapsed = time.monotonic() - t0
    assert "Error" not in text and "failed" not in text, text
    assert elapsed < 6, f"{tool} took {elapsed:.1f}s"


async def test_large_pdf_download_is_intact(srv, sites):
    sites.big_pdf = True
    text = (await srv.call_tool("ieee_download", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
    assert "Downloaded PDF" in text, text
    saved = next((Path.cwd() / "downloads").iterdir()).read_bytes()
    assert saved == fake_sites.BIG_PDF_BYTES
