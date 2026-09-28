from pathlib import Path

import pytest

import server


def test_unique_path_sanitizes_and_numbers(tmp_path):
    first = server._unique_path(tmp_path, 'A: "B"/C?', ".pdf")
    assert first.name == "A BC.pdf"
    first.write_bytes(b"x")
    assert server._unique_path(tmp_path, 'A: "B"/C?', ".pdf").name == "A BC (2).pdf"


def test_empty_title_gets_fallback_name(tmp_path):
    assert server._unique_path(tmp_path, "", ".pdf").name.startswith("paper_")


@pytest.mark.anyio
async def test_ieee_same_title_downloads_twice(srv, sites):
    for _ in range(2):
        text = (await srv.call_tool("ieee_download", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
        assert "Downloaded PDF" in text, text
    names = sorted(p.name for p in (Path.cwd() / "downloads").iterdir())
    assert names == ["IEEE Doc 1001 (2).pdf", "IEEE Doc 1001.pdf"]


@pytest.mark.anyio
async def test_detail_shows_title_and_titled_download_hint(srv, sites):
    text = (await srv.call_tool("ieee_detail", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
    assert "**IEEE Doc 1001**" in text
    assert 'title="IEEE Doc 1001"' in text
