import pytest

from carsi_search.databases.ieee import IeeeAdapter
from carsi_search.databases.sciencedirect import ScienceDirectAdapter


def test_ieee_url_has_page_number():
    url = IeeeAdapter.build_search_url("deep learning", 3)
    assert "queryText=deep%20learning" in url and "pageNumber=3" in url


def test_sd_url_has_offset():
    assert "offset=50" in ScienceDirectAdapter.build_search_url("x", 3)
    assert "offset" not in ScienceDirectAdapter.build_search_url("x", 1)


@pytest.mark.anyio
async def test_ieee_page_2(srv, sites):
    text = (await srv.call_tool("ieee_search", {"query": "radar", "page": 2}))[0].text
    assert "IEEE P2 Paper 1" in text and "IEEE P1 Paper 1" not in text, text


@pytest.mark.anyio
async def test_sd_page_2(srv, sites):
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar", "page": 2}))[0].text
    assert "SD O25 Paper 1" in text and "SD O0 Paper" not in text, text


@pytest.mark.anyio
async def test_cnki_page_3(srv, sites):
    text = (await srv.call_tool("cnki_search", {"query": "雷达", "page": 3}))[0].text
    assert "P3R1" in text and "P1R1" not in text and "3/10" in text, text


@pytest.mark.anyio
async def test_cnki_far_page_uses_next_button(srv, sites):
    sites.cnki_delay_ms = 300
    text = (await srv.call_tool("cnki_search", {"query": "雷达", "page": 8}))[0].text
    assert "P8R1" in text, text


@pytest.mark.anyio
async def test_cnki_missing_page_is_an_error(srv, sites):
    sites.cnki_delay_ms = 200
    text = (await srv.call_tool("cnki_search", {"query": "雷达", "page": 11}))[0].text
    assert "翻页失败" in text and "P1R1" not in text, text


@pytest.mark.anyio
async def test_cnki_sort_waits_for_refresh(srv, sites):
    text = (await srv.call_tool("cnki_search", {"query": "雷达", "sort": "date"}))[0].text
    assert "[PT]" in text, text
