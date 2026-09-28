"""Capture trimmed snapshots of the real IEEE / ScienceDirect data the adapters read.

Run from cnki-ieee-download/ (uses the tool's own browser):  python tests/capture_fixtures.py
Writes tests/fixtures/*. Keeps only public bibliographic data: no page header,
account, institution or userInfo. Re-run when a site changes its layout.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

OUT = Path(__file__).resolve().parent / "fixtures"
REC_KEYS = ["articleNumber", "articleTitle", "authors", "publicationTitle", "publicationYear",
            "abstract", "doi", "documentLink", "pdfLink", "contentType"]
META_KEYS = ["title", "displayDocTitle", "authors", "abstract", "doi", "publicationTitle",
             "publicationYear", "publicationDate", "conferenceDate", "volume", "issue",
             "startPage", "endPage", "issn", "keywords", "pdfUrl", "articleNumber"]
STRIP_JS = r"""(sel) => { const el = document.querySelector(sel); if (!el) return '';
  const c = el.cloneNode(true); c.querySelectorAll('script,style,svg').forEach(n => n.remove());
  return c.outerHTML; }"""
CHAIN_JS = r"""(sel) => { let el = document.querySelector(sel), out = [];
  for (let i = 0; el && i < 8; i++, el = el.parentElement) out.push(el.tagName + '.' + el.className);
  return out.join(' < '); }"""


def dump(name, data):
    OUT.mkdir(exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
    text = re.sub(r"md5=[0-9a-f]{32}", "md5=0", text)   # per-session access token in SD PDF links
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"wrote {name} ({len(text)} chars)")


async def capture_ieee(page):
    xhrs = []
    page.on("response", lambda r: xhrs.append(r) if r.request.resource_type in ("xhr", "fetch") else None)
    await page.goto("https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true"
                    "&queryText=radar%20signal%20processing&ranges=2020_2022_Year", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for r in xhrs:
        print("XHR", r.request.method, r.url[:120])
    api = next(r for r in xhrs if "/rest/search" in r.url and r.request.method == "POST")
    print("payload:", (api.request.post_data or "")[:400])
    body = await api.json()
    print("top-level keys:", list(body))
    recs = [{k: r.get(k) for k in REC_KEYS if k in r} for r in body.get("records", [])[:3]]
    for r in recs:
        r["authors"] = [{"preferredName": a.get("preferredName"), "normalizedName": a.get("normalizedName")}
                        for a in r.get("authors") or []]
    print("years with ranges=2020_2022:", [r.get("publicationYear") for r in body.get("records", [])])
    dump("ieee_search.json", {k: body.get(k) for k in ("totalRecords", "totalPages", "startRecord", "endRecord")}
         | {"records": recs})
    await page.goto("https://ieeexplore.ieee.org" + recs[0]["documentLink"], wait_until="domcontentloaded")
    await page.wait_for_function("() => window.xplGlobal && xplGlobal.document && xplGlobal.document.metadata",
                                 timeout=30000)
    meta = await page.evaluate("() => xplGlobal.document.metadata")
    print("metadata keys:", sorted(meta))
    keep = {k: meta[k] for k in META_KEYS if k in meta}
    keep["authors"] = [{"name": a.get("name")} for a in keep.get("authors") or []]
    dump("ieee_metadata.json", keep)


async def capture_sd(page):
    await page.goto("https://www.sciencedirect.com/search?qs=lithium%20battery%20degradation&show=25"
                    "&date=2020-2022", wait_until="domcontentloaded")
    await page.wait_for_selector("a.result-list-title-link", timeout=30000)
    print("title link chain:", await page.evaluate(CHAIN_JS, "a.result-list-title-link"))
    items = await page.evaluate(r"""() => Array.from(document.querySelectorAll('li.ResultItem')).slice(0, 3)
        .map(li => { const c = li.cloneNode(true); c.querySelectorAll('script,style,svg').forEach(n => n.remove());
                     return c.outerHTML; })""")
    total = await page.evaluate(r"""() => { for (const el of document.querySelectorAll('h1,h2,span,div'))
        if (/^\s*[\d,]+\s+results?\s*$/i.test(el.innerText || '')) return el.outerHTML; return ''; }""")
    dump("sd_search_items.html", total + "\n<ol class='search-result-wrapper'>\n" + "\n".join(items) + "\n</ol>")
    first = await page.evaluate("() => document.querySelector('a.result-list-title-link').href")
    await page.goto(first, wait_until="domcontentloaded")
    await page.wait_for_selector("h1", timeout=30000)
    await page.wait_for_selector("a.accessbar-utility-link[href*='pdfft']", timeout=20000)   # rendered late
    metas = await page.evaluate(r"""() => Array.from(document.querySelectorAll(
        'meta[name^="citation_"], meta[name="dc.identifier"]')).map(m => m.outerHTML).join('\n')""")
    parts = [f"<!-- citation meta -->\n{metas}"]
    for sel in [".publication-title", "h1", "#author-group", "#abstracts", ".keywords-section",
                "a.accessbar-utility-link[href*='pdfft']"]:
        html = await page.evaluate(STRIP_JS, sel)
        print(f"{sel}: {'found' if html else 'MISSING'}")
        if html:
            parts.append(f"<!-- {sel} -->\n{html}")
    doi = await page.evaluate(r"""() => { const a = Array.from(document.querySelectorAll('a[href^="https://doi.org/"]'))
        .find(a => /^10\./.test((a.textContent || '').trim())); return a ? a.outerHTML : ''; }""")
    print(f"article doi link: {'found' if doi else 'MISSING'}")
    parts.append(f"<!-- article doi link -->\n{doi}")
    dump("sd_article.html", "\n".join(parts))


async def main():
    page, err = await server._ensure_page("ieee")
    assert not err, err
    try:
        await capture_ieee(page)
        await capture_sd(page)
    finally:
        await page.close()
        await server._auth.stop()

asyncio.run(main())
