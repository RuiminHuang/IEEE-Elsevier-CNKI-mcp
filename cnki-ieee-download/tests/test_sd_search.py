import time

import pytest

pytestmark = pytest.mark.anyio


async def test_sd_search_keeps_results_without_pdf_in_page_order(srv, sites):
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar"}))[0].text
    positions = [text.index(f"**SD O0 Paper {i}**") for i in range(1, 11)]
    assert positions == sorted(positions)
    assert "Year: 1998" in text
    assert text.count("PDF: 无下载链接") == 3 and text.count("PDF: 可下载") == 7


async def test_sd_search_without_results_returns_at_once(srv, sites):
    await srv._ensure_page("sciencedirect")   # exclude connection setup from the timing
    sites.sd_no_results = True
    t0 = time.monotonic()
    text = (await srv.call_tool("sciencedirect_search",
                                {"query": "radar", "journal": "Journal of Power Sources"}))[0].text
    elapsed = time.monotonic() - t0
    assert text.startswith("No papers found."), text
    assert elapsed < 6, f"took {elapsed:.1f}s"


async def test_sd_unknown_journal_is_reported_at_once(srv, sites):
    await srv._ensure_page("sciencedirect")   # exclude connection setup from the timing
    sites.sd_unknown_journal = True
    t0 = time.monotonic()
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar", "journal": "No Such Journal"}))[0].text
    elapsed = time.monotonic() - t0
    assert text.startswith("Search failed: ScienceDirect: Sorry – your search could not be run. "
                           "Journal or book title: Entry not recognized."), text
    assert elapsed < 6, f"took {elapsed:.1f}s"
