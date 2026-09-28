"""Fake IEEE Xplore / ScienceDirect / CNKI pages for offline tests.

Only the DOM the adapters read is reproduced. Pages are served through
context.route(), so the adapters keep navigating to their real URLs.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

FAKE_HOSTS = re.compile(
    r"^https://(ieeexplore\.ieee\.org|www\.sciencedirect\.com|pdf\.sciencedirectassets\.com|kns\.cnki\.net)/"
)
FILLER = "<p>" + "Lorem ipsum dolor sit amet. " * 20 + "</p>"
PDF_BYTES = b"%PDF-1.4\n% fake paper\n" + b"0" * 2048 + b"\n%%EOF\n"
CAJ_BYTES = b"CAJ\x00fake caj " + b"1" * 2048
SLOW_BYTES = b"%PDF-1.4\n" + b"s" * 600_000


@dataclass
class FakeState:
    logged_in: dict = field(default_factory=lambda: {"ieee": True, "sciencedirect": True, "cnki": True})
    delays: dict = field(default_factory=dict)   # URL substring -> seconds before responding
    cnki_delay_ms: int = 1200                    # CNKI AJAX refresh delay
    cnki_captcha: bool = False
    sd_challenge: bool = False
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
        status, ctype, body = _respond(url, state)
        try:
            await route.fulfill(status=status, content_type=ctype, body=body)
        except Exception:
            pass  # request was aborted by a newer navigation

    await context.route(FAKE_HOSTS, handler)


def _respond(url: str, st: FakeState):
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if u.netloc == "ieeexplore.ieee.org":
        return _ieee(u.path, q, st)
    if u.netloc == "www.sciencedirect.com":
        return _sd(u.path, q, st)
    if u.netloc == "pdf.sciencedirectassets.com":
        if st.sd_challenge:
            return 200, "text/html", _html("<h1>Just a moment...</h1>")
        return 200, "text/plain", PDF_BYTES  # text/plain keeps headless Chrome from opening a PDF viewer
    return _cnki(u.path, q, st)


# ── IEEE ──

def _ieee(path, q, st):
    header = ("<div>Access provided by: Test University <a>Sign Out</a></div>"
              if st.logged_in["ieee"] else "<a>Institutional Sign In</a>")
    if path.startswith("/search/searchresult.jsp"):
        page = int(q.get("pageNumber", "1"))
        start = (page - 1) * 25 + 1
        items = "".join(
            f"<div class='result-item'><h3><a href='https://ieeexplore.ieee.org/document/{page}00{i}/'>"
            f"IEEE P{page} Paper {i}</a></h3><p class='author'>Author {i}</p>"
            f"<span class='year'>Year: 2023</span><div class='description'>Abstract {i}</div></div>"
            for i in range(1, 4))
        body = (f"{header}<div>Showing {start}-{start + 24} of 1,234 results for {q.get('queryText', '')}</div>"
                f"<div class='List-results-items'>{items}</div>")
        return 200, "text/html", _html(body)
    m = re.match(r"/document/(\d+)", path)
    if m:
        doc = m.group(1)
        body = (f"{header}<h1 class='document-title'>IEEE Doc {doc}</h1>"
                f"<div class='authors-info'><a>Alice</a></div>"
                f"<div class='abstract-text'>Abstract of {doc}</div>"
                f"<a href='https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={doc}'>PDF</a>")
        return 200, "text/html", _html(body)
    if path.startswith("/stampPDF/getPDF.jsp"):
        if not st.logged_in["ieee"]:
            return 200, "text/html", _html("<h1>Sign in to access this document</h1>")
        return 200, "application/pdf", PDF_BYTES
    return 200, "text/html", _html(f"{header}<div>IEEE Xplore home</div>")


# ── ScienceDirect ──

def _sd(path, q, st):
    header = ("<div>Access through <b>Test University</b></div>"
              if st.logged_in["sciencedirect"] else "<a>Sign in</a><a>Register</a>")
    if path == "/search":
        offset = int(q.get("offset", "0"))
        items = []
        for i in range(1, 11):
            pii = f"S{offset + i:010d}"
            year = "1998" if i == 2 else "2021"
            has_pdf = i % 2 == 1 or i > 6          # papers 2, 4, 6 have no PDF link
            pdf = (f"<a class='download-link' href='https://www.sciencedirect.com/science/article/pii/{pii}"
                   f"/pdfft?md5=x&pid=1-s2.0-{pii}-main.pdf'>View PDF</a>" if has_pdf else "")
            items.append(
                f"<li class='ResultItem'><h2><a class='result-list-title-link' "
                f"href='https://www.sciencedirect.com/science/article/pii/{pii}'>SD O{offset} Paper {i}</a></h2>"
                f"<div class='Authors'>Author {i}</div><span class='srctitle-date-fields'>Journal X, {year}</span>"
                f"{pdf}</li>")
        body = f"{header}<h1>1,234 results</h1><ol>{''.join(items)}</ol>"
        return 200, "text/html", _html(body)
    m = re.match(r"/science/article/pii/([A-Z0-9]+)(/pdfft)?", path)
    if m and m.group(2):
        target = f"https://pdf.sciencedirectassets.com/{m.group(1)}.pdf"
        return 200, "text/html", _html(f"<script>location.replace('{target}')</script>")
    if m:
        pii = m.group(1)
        body = (f"{header}<h1>SD Article {pii}</h1><div class='author-group'>Alice, Bob</div>"
                f"<div id='abstracts'>Summary of {pii}</div>"
                f"<a class='download-link' href='https://www.sciencedirect.com/science/article/pii/{pii}"
                f"/pdfft?md5=x&pid=1-s2.0-{pii}-main.pdf'>View PDF</a>")
        return 200, "text/html", _html(body)
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
const TOTAL_PAGES = 10, DELAY = __DELAY__;
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
    return (f"<div class='brief'><h1>{title} 网络首发</h1>"
            "<h3 class='author'><a>张三1</a><a>李四2</a></h3>"
            "<h3 class='author'><a>测试大学</a></h3><span class='icon-shoufa'></span></div>"
            "<div class='abstract-text'>这是摘要。</div>"
            "<p class='keywords'><a>雷达;</a><a>测试;</a></p>"
            f"<div class='operate-btn'>{links}</div>")


def _cnki(path, q, st):
    header = ("<div>Test University 欢迎您 <a>退出</a></div>" if st.logged_in["cnki"]
              else "<a>机构登录</a><a>校外访问</a>")
    captcha = CAPTCHA if st.cnki_captcha else HIDDEN_CAPTCHA
    grid = lambda html: html.replace("__DELAY__", str(st.cnki_delay_ms))
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
