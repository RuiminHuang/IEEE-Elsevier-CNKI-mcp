"""
IEEE Xplore database adapter.

Search reads the JSON the results page itself requests (POST /rest/search);
detail reads window.xplGlobal.document.metadata embedded in document pages.
Both are structured data, so no DOM selectors are needed.
"""

import re
from urllib.parse import quote

from .base import BaseAdapter, year_range

_MARKUP = re.compile(r"\[::|::\]|<[^>]+>")   # search highlights "[::radar::]" and inline HTML
_SKIP_KEYWORD_TYPES = {"Index Terms"}         # long machine-generated list


def _clean(value) -> str:
    return re.sub(r"\s+", " ", _MARKUP.sub("", str(value or ""))).strip()


def parse_search_record(rec: dict) -> dict:
    """One record of the /rest/search response -> paper dict for server.handle_search."""
    number = str(rec.get("articleNumber") or "")
    names = [_clean(a.get("preferredName") or a.get("normalizedName")) for a in rec.get("authors") or []]
    return {
        "title": _clean(rec.get("articleTitle")),
        "url": f"https://ieeexplore.ieee.org/document/{number}/" if number else "",
        "authors": "; ".join(n for n in names if n),
        "year": _clean(rec.get("publicationYear")),
        "source": _clean(rec.get("publicationTitle")),
        "abstract": _clean(rec.get("abstract"))[:300],
    }


def parse_metadata(meta: dict) -> dict:
    """xplGlobal.document.metadata -> detail dict for server.handle_detail."""
    keywords = []
    for group in meta.get("keywords") or []:
        if group.get("type") in _SKIP_KEYWORD_TYPES:
            continue
        for k in group.get("kwd") or []:
            if _clean(k) and _clean(k) not in keywords:
                keywords.append(_clean(k))
    pdf = meta.get("pdfUrl") or ""
    return {
        "title": _clean(meta.get("title") or meta.get("displayDocTitle")),
        "authors": [_clean(a.get("name")) for a in meta.get("authors") or [] if a.get("name")],
        "abstract": _clean(meta.get("abstract")),
        "doi": _clean(meta.get("doi")),
        "venue": _clean(meta.get("publicationTitle")),
        "year": _clean(meta.get("publicationYear")),
        "volume": _clean(meta.get("volume")),
        "pages": "-".join(p for p in (_clean(meta.get("startPage")), _clean(meta.get("endPage"))) if p),
        "issn": ", ".join(_clean(i.get("value")) for i in meta.get("issn") or [] if i.get("value")),
        "pubDate": _clean(meta.get("publicationDate") or meta.get("conferenceDate")),
        "keywords": keywords,
        "pdfUrl": "https://ieeexplore.ieee.org" + pdf if pdf.startswith("/") else pdf,
    }


class IeeeAdapter(BaseAdapter):
    name = "ieee"
    home_url = "https://ieeexplore.ieee.org/"
    PAGE_SIZE = 25

    @staticmethod
    def build_search_url(query: str, page: int = 1, year_start=None, year_end=None) -> str:
        url = ("https://ieeexplore.ieee.org/search/searchresult.jsp?"
               f"newsearch=true&queryText={quote(query)}&pageNumber={int(page)}")
        years = year_range(year_start, year_end)
        return url + (f"&ranges={years[0]}_{years[1]}_Year" if years else "")

    async def search(self, query: str, **kwargs) -> dict:
        page_num = int(kwargs.get("page") or 1)
        url = self.build_search_url(query, page_num, kwargs.get("year_start"), kwargs.get("year_end"))
        try:
            async with self.page.expect_response(
                    lambda r: "/rest/search" in r.url and r.request.method == "POST",
                    timeout=30000) as info:
                await self._navigate(url)
            data = await (await info.value).json()
        except Exception as e:
            return {"success": False, "error": f"IEEE 搜索接口没有返回结果（可能出现了验证页）: {e}"}

        start = data.get("startRecord")   # 0-based
        per_page = data.get("recordsPerPage") or self.PAGE_SIZE
        if page_num > 1 and isinstance(start, int) and start < (page_num - 1) * per_page:
            return {"success": False, "error": f"翻页未生效：请求第 {page_num} 页，接口返回的是第 1 页"}
        total = data.get("totalRecords")
        return {
            "success": True,
            "total": f"{total:,}" if isinstance(total, int) else str(total or ""),
            "papers": [parse_search_record(r) for r in data.get("records") or []],
        }

    async def detail(self, url: str, **kwargs) -> dict:
        await self._navigate(url)
        try:
            await self.page.wait_for_function(
                "() => !!(window.xplGlobal && xplGlobal.document && xplGlobal.document.metadata)",
                timeout=20000)
        except Exception:
            return {"success": False, "error": "IEEE 详情页没有加载出论文元数据（xplGlobal.document.metadata）"}
        meta = await self.page.evaluate("() => xplGlobal.document.metadata")
        return {"success": True, **parse_metadata(meta)}
