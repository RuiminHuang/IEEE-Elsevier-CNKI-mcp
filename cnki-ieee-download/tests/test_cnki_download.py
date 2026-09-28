from pathlib import Path

import pytest

import fake_sites

pytestmark = pytest.mark.anyio


def _downloads() -> list[str]:
    d = Path.cwd() / "downloads"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


async def _download(srv, url):
    return (await srv.call_tool("cnki_download", {"url": url}))[0].text


async def test_pdf_download_named_by_title(srv, http_site):
    text = await _download(srv, f"{http_site}/detail/pdf")
    assert "PDF 下载成功" in text, text
    assert _downloads() == ["测试论文PDF.pdf"]
    assert (Path.cwd() / "downloads" / "测试论文PDF.pdf").read_bytes() == fake_sites.PDF_BYTES


async def test_caj_only_download(srv, http_site):
    text = await _download(srv, f"{http_site}/detail/caj")
    assert "CAJ 下载成功" in text, text
    assert (Path.cwd() / "downloads" / "测试论文CAJ.caj").read_bytes() == fake_sites.CAJ_BYTES


async def test_html_response_is_rejected(srv, http_site):
    text = await _download(srv, f"{http_site}/detail/expired")
    assert "不是有效的 PDF/CAJ" in text, text
    assert _downloads() == []


async def test_slow_download_is_complete(srv, http_site):
    text = await _download(srv, f"{http_site}/detail/slow")
    assert "下载成功" in text, text
    assert (Path.cwd() / "downloads" / "测试论文慢速.pdf").read_bytes() == fake_sites.SLOW_BYTES


async def test_same_title_is_not_overwritten(srv, http_site):
    for _ in range(2):
        await _download(srv, f"{http_site}/detail/pdf")
    assert _downloads() == ["测试论文PDF (2).pdf", "测试论文PDF.pdf"]
