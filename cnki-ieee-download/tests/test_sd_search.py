import pytest

pytestmark = pytest.mark.anyio


async def test_sd_search_keeps_results_without_pdf_in_page_order(srv, sites):
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar"}))[0].text
    positions = [text.index(f"**SD O0 Paper {i}**") for i in range(1, 11)]
    assert positions == sorted(positions)
    assert "Year: 1998" in text
    assert text.count("PDF: 无下载链接") == 3 and text.count("PDF: 可下载") == 7
