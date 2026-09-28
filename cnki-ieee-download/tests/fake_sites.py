"""Fake IEEE Xplore / ScienceDirect / CNKI pages for offline tests.

Only the DOM the adapters read is reproduced. Pages are served through
context.route(), so the adapters keep navigating to their real URLs.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent / "fixtures"

FAKE_HOSTS = re.compile(
    r"^https://(ieeexplore\.ieee\.org|www\.sciencedirect\.com|pdf\.sciencedirectassets\.com|kns\.cnki\.net)/"
)
FILLER = "<p>" + "Lorem ipsum dolor sit amet. " * 20 + "</p>"
PDF_BYTES = b"%PDF-1.4\n% fake paper\n" + b"0" * 2048 + b"\n%%EOF\n"
CAJ_BYTES = b"CAJ\x00fake caj " + b"1" * 2048
SLOW_BYTES = b"%PDF-1.4\n" + b"s" * 600_000
BIG_PDF_BYTES = b"%PDF-1.4\n" + bytes(range(256)) * 24_000   # ~6 MB, every byte value
# Keeps a page from ever reaching "network idle", like the analytics on the live sites.
BUSY_SCRIPT = "<script>setInterval(() => fetch('/__ping?' + Date.now()).catch(() => {}), 250)</script>"


@dataclass
class FakeState:
    logged_in: dict = field(default_factory=lambda: {"ieee": True, "sciencedirect": True, "cnki": True})
    delays: dict = field(default_factory=dict)   # URL substring -> seconds before responding
    cnki_delay_ms: int = 1200                    # CNKI AJAX refresh delay
    cnki_total_pages: int = 10
    cnki_captcha: bool = False
    sd_challenge: str = ""   # "", "cloudflare" or "elsevier" (page shown on the PDF domain)
    busy_network: bool = False   # inject BUSY_SCRIPT into every HTML page
    big_pdf: bool = False        # IEEE getPDF returns BIG_PDF_BYTES
    requests: list = field(default_factory=list)
    connections: int = 0


def _html(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'></head><body>{body}{FILLER}</body></html>"


async def install(context, state: FakeState):
    async def handler(route):
        url = route.request.url
        state.requests.append(url)
        for key, secs in state.delays.items():
            if key in url:
                await asyncio.sleep(secs)
        status, ctype, body = _respond(route.request, state)
        if state.busy_network and ctype.startswith("text/html") and isinstance(body, str):
            body = body.replace("</body>", BUSY_SCRIPT + "</body>")
        try:
            await route.fulfill(status=status, content_type=ctype, body=body)
        except Exception:
            pass  # request was aborted by a newer navigation

    await context.route(FAKE_HOSTS, handler)


def _respond(request, st: FakeState):
    u = urlparse(request.url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if u.path == "/__ping":
        return 204, "text/plain", ""
    if u.netloc == "ieeexplore.ieee.org":
        return _ieee(request, u.path, q, st)
    if u.netloc == "www.sciencedirect.com":
        return _sd(u.path, q, st)
    if u.netloc == "pdf.sciencedirectassets.com":
        if st.sd_challenge == "cloudflare":
            return 200, "text/html", _html("<h1>Just a moment...</h1>")
        if st.sd_challenge == "elsevier":   # as seen live on pdf.sciencedirectassets.com
            return 200, "text/html", ("<!DOCTYPE html><html><head><title>Security verification</title></head>"
                                      "<body><h1>Request Verification: In Progress</h1>"
                                      "<p>If you are unable to access your content please try again.</p></body></html>")
        if st.sd_challenge == "elsevier_late":   # same page, but its text renders after a while
            return 200, "text/html", ("<!DOCTYPE html><html><head><title>Security verification</title></head>"
                                      "<body><script>setTimeout(() => document.body.innerHTML ="
                                      " '<h1>Request Verification: In Progress</h1>', 4000)</script></body></html>")
        return 200, "text/plain", PDF_BYTES  # text/plain keeps headless Chrome from opening a PDF viewer
    return _cnki(u.path, q, st)


# ── IEEE ──
# Mirrors the live site: the results page fetches its data with POST /rest/search
# (JSON body, "ranges": ["2020_2022_Year"]); document pages embed xplGlobal.document.metadata.
# Record and metadata shapes come from the real snapshots in fixtures/.

IEEE_SEARCH = json.loads((FIXTURES / "ieee_search.json").read_text(encoding="utf-8"))
IEEE_META = json.loads((FIXTURES / "ieee_metadata.json").read_text(encoding="utf-8"))
_IEEE_RESULTS_PAGE = """<div class='List-results-items'></div>
<script>
const p = new URLSearchParams(location.search);
const body = {newsearch: true, queryText: p.get('queryText') || '', highlight: true, returnType: 'SEARCH'};
if (+p.get('pageNumber') > 1) body.pageNumber = +p.get('pageNumber');
if (p.get('ranges')) body.ranges = [p.get('ranges')];
fetch('/rest/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
</script>"""


def _ieee_search_api(post_data):
    body = json.loads(post_data or "{}")
    page = int(body.get("pageNumber") or 1)
    lo = hi = 2023
    for r in body.get("ranges") or []:
        m = re.match(r"(\d{4})_(\d{4})_Year", r)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
    records = []
    for i in range(1, 4):
        rec = dict(IEEE_SEARCH["records"][0])
        rec.update(articleTitle=f"IEEE P{page} Paper {i}", articleNumber=f"{page}00{i}",
                   documentLink=f"/document/{page}00{i}/", publicationYear=str(lo + (i - 1) % (hi - lo + 1)))
        records.append(rec)
    return {**IEEE_SEARCH, "records": records, "totalRecords": 1234,
            "startRecord": (page - 1) * 25, "recordsPerPage": 25}


def _ieee(request, path, q, st):
    header = ("<div>Access provided by: Test University <a>Sign Out</a></div>"
              if st.logged_in["ieee"] else "<a>Institutional Sign In</a>")
    if path.startswith("/search/searchresult.jsp"):
        return 200, "text/html", _html(header + _IEEE_RESULTS_PAGE)
    if path == "/rest/search" and request.method == "POST":
        return 200, "application/json", json.dumps(_ieee_search_api(request.post_data))
    m = re.match(r"/document/(\d+)", path)
    if m:
        doc = m.group(1)
        meta = {**IEEE_META, "title": f"IEEE Doc {doc}", "abstract": f"Abstract of {doc}",
                "pdfUrl": f"/stamp/stamp.jsp?tp=&arnumber={doc}", "articleNumber": doc}
        script = ("<script>window.xplGlobal = {document: {metadata: %s}};</script>"
                  % json.dumps(meta).replace("</", "<\\/"))
        return 200, "text/html", _html(f"{header}<h1 class='document-title'>IEEE Doc {doc}</h1>{script}")
    if path.startswith("/stampPDF/getPDF.jsp"):
        if not st.logged_in["ieee"]:
            return 200, "text/html", _html("<h1>Sign in to access this document</h1>")
        return 200, "application/pdf", BIG_PDF_BYTES if st.big_pdf else PDF_BYTES
    return 200, "text/html", _html(f"{header}<div>IEEE Xplore home</div>")


# ── ScienceDirect ──
# Markup mirrors the live snapshots in fixtures/sd_search_items.html and sd_article.html.

SD_SNAPSHOT = (FIXTURES / "sd_search_items.html").read_text(encoding="utf-8")


def _sd_item(pii: str, title: str, authors: list, journal: str, date: str, has_pdf: bool) -> str:
    names = "".join(f"<li><span class='author text-xs'>{a}</span></li>" for a in authors)
    pdf = (f"<a class='anchor download-link' target='_blank' href='/science/article/pii/{pii}"
           f"/pdfft?pid=1-s2.0-{pii}-main.pdf'><span class='preview-link-text'>View PDF</span></a>"
           if has_pdf else "")
    return (f"<li class='ResultItem col-xs-24 push-m' data-doi='10.1016/test.{pii}'>"
            f"<div class='result-item-container'><div class='result-item-content'>"
            f"<h2><span><a class='anchor result-list-title-link' href='/science/article/pii/{pii}'>"
            f"<span class='anchor-text'><span>{title}</span></span></a></span></h2>"
            f"<div class='SubType hor text-xs'><span class='srctitle-date-fields'><span>"
            f"<a class='anchor subtype-srctitle-link' href='/journal/x'><span>{journal}</span></a></span>"
            f"<span>{date}</span></span></div>"
            f"<ol class='Authors hor reduce-list'>{names}</ol>"
            f"<div class='PreviewLinks'>{pdf}</div></div></div></li>")


def _sd_article(pii: str) -> str:
    pdf = f"/science/article/pii/{pii}/pdfft?md5=0&pid=1-s2.0-{pii}-main.pdf"
    return (f"<meta name='citation_title' content='SD Article {pii}'>"
            f"<meta name='citation_journal_title' content='Journal X'>"
            f"<meta name='citation_volume' content='12'><meta name='citation_issn' content='1234-5678'>"
            f"<meta name='citation_doi' content='10.1016/test.{pii}'>"
            f"<meta name='citation_publication_date' content='2021/03/01'>"
            f"<h2 class='publication-title'><a><span class='anchor-text'>Journal X</span></a></h2>"
            f"<h1 class='content-title'><span class='title-text'>SD Article {pii}</span></h1>"
            f"<div class='author-group' id='author-group'><span class='sr-only'>Author links open overlay panel</span>"
            f"<button><span class='react-xocs-alternative-link'><span class='given-name'>Alice</span> "
            f"<span class='text surname'>Smith</span></span><span class='author-ref'><sup>a</sup></span></button>, "
            f"<button><span class='react-xocs-alternative-link'><span class='given-name'>Bob</span> "
            f"<span class='text surname'>Jones</span></span><span class='author-ref'><sup>b</sup></span></button></div>"
            f"<div class='abstracts' id='abstracts'>"
            f"<div class='abstract author-highlights' id='abs0001'><h2>Highlights</h2>"
            f"<div class='abstract author'><ul><li>Highlight one.</li></ul></div></div>"
            f"<div class='abstract author' id='abs0002'><h2>Abstract</h2>"
            f"<div class='abstract author'><div>Summary of {pii}</div></div></div></div>"
            f"<div class='keywords-section'><div class='keyword'><span>Batteries</span></div><span>; </span>"
            f"<div class='keyword'><span>Degradation</span></div></div>"
            f"<a class='anchor pdf link' target='_blank' href='/science/article/pii/SREF000001/pdfft'>View PDF</a>"
            # like the live page, the access bar's own "View PDF" button renders late
            f"<script>setTimeout(() => document.body.insertAdjacentHTML('beforeend',"
            f" '<a class=\"link-button accessbar-utility-link\" target=\"_blank\" href=\"{pdf}\">View PDF</a>'),"
            f" 1500)</script>")


def _sd(path, q, st):
    header = ("<div>Access through <b>Test University</b></div>"
              if st.logged_in["sciencedirect"] else "<a>Sign in</a><a>Register</a>")
    if path == "/search":
        if q.get("qs") == "__snapshot__":
            return 200, "text/html", _html(header + SD_SNAPSHOT)
        offset = int(q.get("offset", "0"))
        span = re.match(r"(\d{4})-(\d{4})$", q.get("date", ""))
        items = []
        for i in range(1, 11):
            pii = f"S{offset + i:010d}"
            if span:   # SD's "date=2020-2022" filter
                lo, hi = int(span.group(1)), int(span.group(2))
                date = f"1 March {lo + (i - 1) % (hi - lo + 1)}"
            else:
                date = "5 May 1998" if i == 2 else "1 March 2021"
            has_pdf = i % 2 == 1 or i > 6          # papers 2, 4, 6 have no PDF link
            items.append(_sd_item(pii, f"SD O{offset} Paper {i}", [f"Alice {i}", f"Bob {i}"],
                                  "Journal X", date, has_pdf))
        body = (f"{header}<h1 class='text-l'><span class='search-body-results-text'>1,234 results</span></h1>"
                f"<ol class='search-result-wrapper'>{''.join(items)}</ol>")
        return 200, "text/html", _html(body)
    m = re.match(r"/science/article/pii/([A-Z0-9]+)(/pdfft)?", path)
    if m and m.group(2) and q.get("stay"):   # an almost empty page on the site (e.g. mid-redirect)
        return 200, "text/html", "<!doctype html><html><body></body></html>"
    if m and m.group(2) and (q.get("forbidden") or ("isDTMRedir" in q and "md5" not in q)):
        # SD's 403 page (live: the untokenised fallback pdfft link gets 403); generic "Sign in" header
        return 403, "text/html", _html("<a>Sign in</a><h1>Access denied</h1>")
    if m and m.group(2):
        target = f"https://pdf.sciencedirectassets.com/{m.group(1)}.pdf"
        return 200, "text/html", _html(f"<script>location.replace('{target}')</script>")
    if m:
        return 200, "text/html", _html(header + _sd_article(m.group(1)))
    return 200, "text/html", _html(f"{header}<div>ScienceDirect home</div>")


# ── CNKI ──

CAPTCHA = ("<div id='tcaptcha_transform_dy' style='position:fixed;top:0;left:0;"
           "width:300px;height:200px'>请完成安全验证</div>")
HIDDEN_CAPTCHA = "<div id='tcaptcha_transform_dy' style='position:fixed;top:-1000000px'></div>"
# Mirrors kns8s: the active sort <li> has classes "DESC cur" / "ASC cur"; the default is
# 发表时间 newest first; clicking the active one flips its direction (FFD is DESC-only).
SORTS = ("<ul id='orderList' class='order'>"
         "<li id='FFD' data-onlydesc='DESC'>相关度</li><li id='PT' class='DESC cur' data-onlydesc='BOTH'>发表时间</li>"
         "<li id='CF' data-onlydesc='BOTH'>被引</li><li id='DFR' data-onlydesc='BOTH'>下载</li></ul>")

# Result grid re-rendered via innerHTML after DELAY ms, like CNKI's AJAX brief list.
_CNKI_GRID = """
<div id="gridTable"></div>
<script>
const TOTAL_PAGES = __TOTAL__, DELAY = __DELAY__;
const state = {q: '', page: 1, sort: 'PT', dir: 'DESC'};
function render() {
  document.querySelectorAll('#orderList li').forEach(li => {
    li.className = li.id === state.sort ? state.dir + ' cur' : '';
  });
  let rows = '';
  for (let i = 1; i <= 3; i++) {
    const id = 'P' + state.page + 'R' + i;
    rows += '<tr><td class="name"><a class="fz14" target="_blank" href="https://kns.cnki.net/kcms2/article/abstract?v=' + id + '">'
      + '[' + state.sort + '-' + state.dir + '] ' + state.q + ' ' + id + '</a></td>'
      + '<td class="author"><a class="KnowledgeNetLink">作者' + i + '</a></td><td class="source"><a>测试期刊</a></td>'
      + '<td class="date">2024-01-0' + i + '</td><td class="quote">' + i + '</td><td class="download">' + (10 * i) + '</td></tr>';
  }
  let pager = '';
  for (let p = Math.max(1, state.page - 2); p <= Math.min(TOTAL_PAGES, state.page + 2); p++) {
    pager += p === state.page ? '<a class="cur">' + p + '</a>'
                              : '<a data-curpage="' + p + '" href="javascript:void(0)">' + p + '</a>';
  }
  if (state.page < TOTAL_PAGES)
    pager += '<a id="PageNext" data-curpage="' + (state.page + 1) + '" href="javascript:void(0)">下一页</a>';
  document.getElementById('gridTable').innerHTML =
    '<div class="pagerTitleCell">共找到 30 条结果</div><span class="countPageMark">' + state.page + '/' + TOTAL_PAGES + '</span>'
    + '<table class="result-table-list"><tbody>' + rows + '</tbody></table><div class="pages">' + pager + '</div>';
}
function load(changes) { setTimeout(() => { Object.assign(state, changes); render(); }, DELAY); }
document.addEventListener('click', e => {
  const pageLink = e.target.closest('[data-curpage]');
  if (pageLink) { load({page: +pageLink.dataset.curpage}); return; }
  const sortLink = e.target.closest('#orderList li');
  if (sortLink) {
    const flip = sortLink.id === state.sort && state.dir === 'DESC' && sortLink.dataset.onlydesc === 'BOTH';
    load({sort: sortLink.id, dir: flip ? 'ASC' : 'DESC', page: 1});
  }
  const btn = e.target.closest('.search-btn');
  if (btn) load({q: document.querySelector('.search-input').value, page: 1});
});
</script>
"""
CNKI_SEARCH = "<input class='search-input' type='text'><input class='search-btn' type='button' value='检索'>" + SORTS + _CNKI_GRID
CNKI_PRO_SEARCH = "<textarea class='search-input'></textarea><input class='search-btn' type='button' value='检索'>" + SORTS + _CNKI_GRID


def _cnki_detail_body(title: str, links: str) -> str:
    return ("<div class='doc-top'><a>测试期刊 .</a></div>"   # live pages show "刊名 ."
            f"<div class='brief'><h1>{title} 网络首发</h1>"
            "<h3 class='author'><a>张三1</a><a>李四2</a></h3>"
            "<h3 class='author'><a>测试大学</a></h3><span class='icon-shoufa'></span></div>"
            "<div class='abstract-text'>这是摘要。</div>"
            "<p class='keywords'><a>雷达;</a><a>测试;</a></p>"
            f"<div class='operate-btn'>{links}</div>")


def _cnki(path, q, st):
    header = ("<div>Test University 欢迎您 <a>退出</a></div>" if st.logged_in["cnki"]
              else "<a>机构登录</a><a>校外访问</a>")
    captcha = CAPTCHA if st.cnki_captcha else HIDDEN_CAPTCHA
    grid = lambda html: (html.replace("__DELAY__", str(st.cnki_delay_ms))
                         .replace("__TOTAL__", str(st.cnki_total_pages)))
    if path.startswith("/kns8s/AdvSearch"):
        return 200, "text/html", _html(header + captcha + grid(CNKI_PRO_SEARCH))
    if path.startswith("/kns8s/search"):
        if st.cnki_captcha:
            return 200, "text/html", _html(header + captcha)   # captcha blocks the search box
        return 200, "text/html", _html(header + captcha + grid(CNKI_SEARCH))
    if path.startswith("/kcms2/article/abstract"):
        return 200, "text/html", _html(header + captcha + _cnki_detail_body(f"Paper {q.get('v', '')}", ""))
    return 200, "text/html", _html(header + "<div>CNKI home</div>")


# ── Local server for real browser downloads (CNKI detail pages + files) ──

class DownloadHandler(BaseHTTPRequestHandler):
    PDF_LINK = "<a id='pdfDown' target='_blank' href='/dl/{0}'>PDF下载</a>"
    CAJ_LINK = "<a id='cajDown' target='_blank' href='/dl/{0}'>CAJ下载</a>"
    PAGES = {
        "/detail/pdf": ("测试论文PDF", PDF_LINK.format("paper.pdf")),
        "/detail/caj": ("测试论文CAJ", CAJ_LINK.format("paper.caj")),
        "/detail/expired": ("测试论文过期", PDF_LINK.format("expired")),
        "/detail/slow": ("测试论文慢速", PDF_LINK.format("slow.pdf")),
    }

    def log_message(self, *args):
        pass

    def _send(self, ctype: str, body: bytes, filename: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f"attachment; filename={filename}")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in self.PAGES:
            title, links = self.PAGES[path]
            self._send("text/html; charset=utf-8", _html(_cnki_detail_body(title, links)).encode("utf-8"))
        elif path == "/dl/paper.pdf":
            self._send("application/pdf", PDF_BYTES, "paper.pdf")
        elif path == "/dl/paper.caj":
            self._send("application/octet-stream", CAJ_BYTES, "paper.caj")
        elif path == "/dl/expired":   # session expired: CNKI answers with an HTML page
            self._send("text/html", b"<!DOCTYPE html><html><body>login</body></html>", "paper.pdf")
        elif path == "/dl/slow.pdf":  # three chunks, 1.5 s apart
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "attachment; filename=slow.pdf")
            self.send_header("Content-Length", str(len(SLOW_BYTES)))
            self.end_headers()
            step = len(SLOW_BYTES) // 3 + 1
            for i in range(0, len(SLOW_BYTES), step):
                self.wfile.write(SLOW_BYTES[i:i + step])
                self.wfile.flush()
                time.sleep(1.5)
        else:
            self.send_response(404)
            self.end_headers()
