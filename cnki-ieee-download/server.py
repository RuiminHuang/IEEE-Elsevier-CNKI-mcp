#!/usr/bin/env python3
"""
学术论文搜索下载 MCP Server — IEEE / ScienceDirect / CNKI 统一入口。

通过 CDP 连接用户真实 Chrome/Edge，自动启动浏览器（如未运行）。
用户手动登录一次，登录状态保存在专用浏览器配置（~/.carsi_chrome_profile）里。

MCP tools (格式: {数据库}_{操作}):
  ieee_login / ieee_search / ieee_detail / ieee_download
  sciencedirect_login / sciencedirect_search / sciencedirect_detail / sciencedirect_download
  cnki_login / cnki_search / cnki_detail / cnki_download
  status / logout

添加新数据库: 编辑 registry.py + 在 databases/ 下创建适配器
"""

import asyncio
import base64
import os
import re
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from carsi_search.engine import CarsiAuth, log
from carsi_search.registry import list_dbs, get_db, get_adapter
from carsi_search.databases.base import is_challenge, year_range
from carsi_search.databases.cnki import CnkiAdapter

from playwright.async_api import Page as PwPage

app = Server("cnki-ieee-download")

_auth: CarsiAuth | None = None
_pages: dict = {}
_locks: dict[str, asyncio.Lock] = {}
DB_LIST = ", ".join(list_dbs())


def _lock_for(key: str) -> asyncio.Lock:
    return _locks.setdefault(key, asyncio.Lock())


def _lock_keys(name: str) -> list[str]:
    """Tools of one database share one browser tab, so they run one at a time.
    logout tears the connection down, so it waits for every database."""
    if name == "logout":
        return list_dbs()
    db = name.split("_", 1)[0]
    return [db] if db in list_dbs() else []


# ══════════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════════

def _db_domain(db: str) -> str:
    return urlparse(get_db(db)["home_url"]).netloc


def _page_alive(page) -> bool:
    # page.url / context.pages are cached values that never raise, so they can't
    # tell whether a tab or the browser is gone; is_closed() can.
    return page is not None and not page.is_closed()


async def _ensure_connection(stale: CarsiAuth | None = None) -> str | None:
    """Ensure a live CDP connection. `stale` is a connection the caller found broken
    even though it still looked alive. Returns error message or None."""
    global _auth, _pages
    async with _lock_for("__conn__"):
        if _auth and _auth.is_alive() and _auth is not stale:
            return None
        if _auth:
            log.info("[CDP] Connection lost, reconnecting...")
            try:
                await _auth.stop()
            except Exception:
                pass
        _auth, _pages = None, {}
        auth = CarsiAuth()
        try:
            await auth.start()   # also restores saved cookies
        except RuntimeError as e:
            return str(e)
        _auth = auth
        return None


async def _ensure_page(db: str):
    """Get a live page for db, reconnecting once if the browser went away.
    Returns (page, error_or_None)."""
    if not get_db(db):
        return None, f"Unknown database: {db}"
    stale = None
    for _ in range(2):
        err = await _ensure_connection(stale)
        if err:
            return None, err
        page = _pages.get(db)
        if not _page_alive(page):
            try:
                # Only ever use a tab this tool opened; never take over one the user is reading.
                page = await _auth.context.new_page()
            except Exception as e:
                log.info(f"[CDP] new_page failed, reconnecting: {e}")
                stale = _auth
                continue
        _pages[db] = page
        return page, None
    return None, "CDP 重连失败"


_LOGIN_HOST_PREFIXES = ("login.", "idp.", "ids.", "fsso.", "auth.", "cas.", "sso.")
_LOGIN_PATH_WORDS = ("login", "wayf", "authserver", "/cas/", "/idp/", "/sso", "shibauth")
MIN_PAGE_TEXT = 100   # less text than this means the page hasn't rendered yet


def _is_login_url(url: str) -> bool:
    """True for login / identity-provider pages. Only host and path are checked,
    so search terms like 'forecasting' in the query string don't count."""
    u = urlparse(url)
    host, path = u.netloc.lower(), u.path.lower()
    return host.startswith(_LOGIN_HOST_PREFIXES) or any(w in path for w in _LOGIN_PATH_WORDS)


def _is_logged_in(db: str, page_text: str) -> bool:
    """Check if user is logged in based on page text keywords."""
    if len(page_text.strip()) < MIN_PAGE_TEXT:
        return False   # blank or still loading: can't tell, so don't claim success
    if is_challenge(page_text):
        return False
    if db == "sciencedirect":
        has_inst = "institutional access via" in page_text.lower()
        has_sign_in = "Sign in" in page_text and "Sign in via" not in page_text
        return has_inst or not has_sign_in
    elif db == "cnki":
        return "机构登录" not in page_text and "校外访问" not in page_text
    else:
        return "Institutional Sign In" not in page_text


def _need_login_response(db: str) -> list[TextContent]:
    """Create standardized login-required response with action prompt."""
    db_config = get_db(db)
    label = db_config["label"] if db_config else db
    home = db_config["home_url"] if db_config else ""

    guides = {
        "cnki": (
            "1. 打开已启动的 Chrome/Edge 浏览器\n"
            "2. 访问 https://kns.cnki.net\n"
            "3. 点击「机构登录」→「校外访问」\n"
            "4. 选择学校并完成认证"
        ),
        "sciencedirect": (
            "1. 打开已启动的 Chrome/Edge 浏览器\n"
            "2. 访问 https://www.sciencedirect.com\n"
            "3. 点击 Sign in → Sign in via your institution\n"
            "4. 完成机构认证"
        ),
        "ieee": (
            "1. 打开已启动的 Chrome/Edge 浏览器\n"
            f"2. 访问 {home}\n"
            "3. 点击 Institutional Sign In\n"
            "4. 完成机构认证"
        ),
    }
    steps = guides.get(db, guides["ieee"])

    return [TextContent(type="text",
        text=f"⚠️ 需要登录 {label}\n\n"
             f"请在浏览器中完成以下操作：\n{steps}\n\n"
             f"登录完成后请告知我，我将重试当前操作。\n\n"
             f"[ACTION_REQUIRED: 请使用 AskUserQuestion 询问用户是否已完成 {label} 登录]")]


def _need_action_response(db: str, action: str) -> list[TextContent]:
    """Create standardized action-required response (Cloudflare, captcha)."""
    db_config = get_db(db)
    label = db_config["label"] if db_config else db
    return [TextContent(type="text",
        text=f"⚠️ 需要手动操作\n\n"
             f"{label} {action}\n"
             f"请在浏览器中手动完成，完成后告知我。\n\n"
             f"[ACTION_REQUIRED: 请使用 AskUserQuestion 询问用户是否已完成操作]")]


async def _check_login(db: str, page) -> str:
    """Open db's home page if needed and report 'ok', 'login' or 'challenge'."""
    try:
        if urlparse(page.url).netloc != _db_domain(db) or _is_login_url(page.url):
            await page.goto(get_db(db)["home_url"], wait_until="domcontentloaded", timeout=30000)
        if _is_login_url(page.url):
            return "login"
        text = await page.evaluate("() => document.body.innerText.slice(0, 5000)")
    except Exception as e:
        log.debug(f"Login check failed for {db}: {e}")
        return "login"
    if is_challenge(text):
        return "challenge"
    return "ok" if _is_logged_in(db, text) else "login"


async def _ensure_logged_in(db: str) -> tuple[PwPage | None, list[TextContent] | None]:
    """Ensure we have a logged-in page for db. Returns (page, error_response_or_None)."""
    page, err = await _ensure_page(db)
    if err or not page:
        return None, [TextContent(type="text", text=err or "CDP 连接失败")]
    state = await _check_login(db, page)
    if state == "ok":
        return page, None
    if state == "challenge":
        return None, _need_action_response(db, "显示了安全验证页面（Cloudflare / Security verification）。")
    return None, _need_login_response(db)


# ══════════════════════════════════════════════════════════════════════
# Tool Definitions
# ══════════════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ── IEEE ──
        Tool(
            name="ieee_login",
            description="Connect Chrome via CDP and check IEEE Xplore login status. Auto-launches Chrome if needed.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="ieee_search",
            description="Search IEEE Xplore. No login needed. Supports paging via 'page'. "
                        "Optional year_start/year_end filter by publication year.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "year_start": {"type": "string", "description": "(Optional) Start year e.g. '2020'"},
                    "year_end": {"type": "string", "description": "(Optional) End year e.g. '2025'"},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="ieee_detail",
            description="Get full paper metadata from an IEEE Xplore document page. No login needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "IEEE paper detail page URL"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="ieee_download",
            description="Download a paper PDF from IEEE Xplore. Requires institutional login (see ieee_login). Saves to downloads/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "IEEE paper detail URL (or direct PDF URL)"},
                    "title": {"type": "string", "description": "Paper title (used as filename)."},
                },
                "required": ["url"]
            }
        ),
        # ── ScienceDirect ──
        Tool(
            name="sciencedirect_login",
            description="Connect Chrome and check ScienceDirect login status. Cloudflare may require manual verification.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="sciencedirect_search",
            description="Search ScienceDirect. No login needed. Supports paging via 'page'. "
                        "Optional year_start/year_end filter by publication year.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "year_start": {"type": "string", "description": "(Optional) Start year e.g. '2020'"},
                    "year_end": {"type": "string", "description": "(Optional) End year e.g. '2025'"},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="sciencedirect_detail",
            description="Get full paper metadata from a ScienceDirect article page. No login needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "ScienceDirect article URL"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="sciencedirect_download",
            description="Download a paper PDF from ScienceDirect. Requires institutional login (see sciencedirect_login); a security check may need manual verification. Saves to downloads/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "ScienceDirect article URL or pdfft URL"},
                    "title": {"type": "string", "description": "Paper title (used as filename)."},
                },
                "required": ["url"]
            }
        ),
        # ── CNKI ──
        Tool(
            name="cnki_login",
            description="Check CNKI login status. User logs in manually in Chrome; this tool only checks and reports.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="cnki_search",
            description=(
                "Search CNKI (中国知网) for papers. "
                "For basic search, only 'query' is needed. "
                "Optional filters (author, journal, year_start, year_end) trigger professional search (专业检索) "
                "using CNKI query syntax: SU=topic AND AU=author AND LY=journal. "
                "Do NOT use author:/journal:/year: syntax — those are not supported by CNKI. No login needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (Chinese or English). Required."},
                    "author": {"type": "string", "description": "(Optional) Filter by author name"},
                    "journal": {"type": "string", "description": "(Optional) Filter by journal/source name"},
                    "year_start": {"type": "string", "description": "(Optional) Start year e.g. '2020'"},
                    "year_end": {"type": "string", "description": "(Optional) End year e.g. '2025'"},
                    "page": {"type": "integer", "description": "Page number (default 1)", "default": 1},
                    "sort": {"type": "string", "description": "Sort (always descending): relevance, date, citations, downloads. CNKI's default is date, newest first"},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="cnki_detail",
            description="Get full paper metadata from a CNKI paper detail page. No login needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL (contains kcms2/article/abstract)"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="cnki_download",
            description="Download a paper PDF (or CAJ if no PDF) from CNKI. Requires CNKI institutional login in the browser.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL"},
                },
                "required": ["url"]
            }
        ),
        # ── Generic ──
        Tool(
            name="status",
            description="Check CDP connection status and list available databases.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="logout",
            description="Disconnect and close the tabs this tool opened. The browser and your logins stay.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]


# ══════════════════════════════════════════════════════════════════════
# Tool Dispatch
# ══════════════════════════════════════════════════════════════════════

async def _dispatch(name: str, args: dict) -> list[TextContent]:
    if name == "ieee_login":             return await handle_login("ieee")
    if name == "ieee_search":            return await handle_search("ieee", args)
    if name == "ieee_detail":            return await handle_detail("ieee", args)
    if name == "ieee_download":          return await handle_download("ieee", args)
    if name == "sciencedirect_login":    return await handle_login("sciencedirect")
    if name == "sciencedirect_search":   return await handle_search("sciencedirect", args)
    if name == "sciencedirect_detail":   return await handle_detail("sciencedirect", args)
    if name == "sciencedirect_download": return await handle_download("sciencedirect", args)
    if name == "cnki_login":             return await handle_login("cnki")
    if name == "cnki_search":            return await handle_cnki_search(args)
    if name == "cnki_detail":            return await handle_cnki_detail(args)
    if name == "cnki_download":          return await handle_cnki_download(args)
    if name == "status":                 return await handle_status()
    if name == "logout":                 return await handle_logout()
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


@app.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    t0 = time.time()
    try:
        async with AsyncExitStack() as stack:
            for key in _lock_keys(name):
                await stack.enter_async_context(_lock_for(key))
            result = await _dispatch(name, args)
        elapsed = time.time() - t0
        if result:
            result[0].text += f"\n\n⏱ {elapsed:.1f}s"
        return result
    except Exception as e:
        log.exception(f"Tool {name} error")
        return [TextContent(type="text", text=f"Error in {name}: {e}")]


# ══════════════════════════════════════════════════════════════════════
# Shared Handlers (IEEE / ScienceDirect / CNKI login)
# ══════════════════════════════════════════════════════════════════════

async def handle_login(db: str) -> list[TextContent]:
    """Connect Chrome and check login status for any database."""
    if db not in list_dbs():
        return [TextContent(type="text", text=f"Unknown database: {db}. Available: {DB_LIST}")]
    page, err = await _ensure_logged_in(db)
    if err:
        return err
    return [TextContent(type="text",
        text=f"✅ 已连接 {get_db(db)['label']}。\n"
             f"URL: {page.url[:120]}\n"
             f"登录状态保存在专用浏览器配置（~/.carsi_chrome_profile）中，下次自动沿用。")]


async def handle_search(db: str, args: dict) -> list[TextContent]:
    """Search papers in IEEE or ScienceDirect. No login needed."""
    page, err = await _ensure_page(db)
    if err or not page:
        return [TextContent(type="text", text=err or "CDP 连接失败")]

    adapter = await get_adapter(db, page)
    result = await adapter.search(args["query"], page=args.get("page", 1),
                                  year_start=args.get("year_start"), year_end=args.get("year_end"))

    if not result.get("success"):
        err = result.get("error", "")
        if err == "captcha":
            return _need_action_response(db, "显示了验证页面。")
        return [TextContent(type="text", text=f"Search failed: {err}")]

    papers = result.get("papers", [])
    if not papers:
        return [TextContent(type="text", text="No papers found.")]

    total = result.get("total", "")
    total_str = f" (total: {total})" if total else ""
    page_num = args.get("page", 1)
    years = year_range(args.get("year_start"), args.get("year_end"))
    year_str = f" [年份={years[0]}-{years[1]}]" if years else ""
    text = f"Page {page_num}, {len(papers)} papers{total_str}{year_str}:\n\n"
    for i, p in enumerate(papers, 1):
        text += f"{i}. **{p.get('title', 'No title')}**\n"
        if p.get('authors'): text += f"   Authors: {p['authors']}\n"
        if p.get('year'): text += f"   Year: {p['year']}\n"
        if p.get('source'): text += f"   Source: {p['source']}\n"
        if p.get('abstract'): text += f"   Abstract: {p['abstract'][:200]}...\n"
        if p.get('hasPdf') is not None: text += f"   PDF: {'可下载' if p['hasPdf'] else '无下载链接'}\n"
        if p.get('url'): text += f"   URL: {p['url']}\n"
        text += "\n"
    text += f"-> Use {db}_detail(url=URL) for full metadata"
    return [TextContent(type="text", text=text)]


async def handle_detail(db: str, args: dict) -> list[TextContent]:
    """Get paper details from IEEE or ScienceDirect. No login needed."""
    page, err = await _ensure_page(db)
    if err or not page:
        return [TextContent(type="text", text=err or "CDP 连接失败")]

    adapter = await get_adapter(db, page)
    result = await adapter.detail(args["url"])

    if not result.get("success"):
        err = result.get("error", "")
        if err == "captcha":
            return _need_action_response(db, "详情页显示了验证页面。")
        return [TextContent(type="text", text=f"Detail failed: {err}")]

    title = result.get("title", "")
    text = f"**{title}**\n\n" if title else ""
    if result.get("abstract"): text += f"**Abstract**\n{result['abstract']}\n\n"
    if result.get("authors"):
        authors = result["authors"] if isinstance(result["authors"], list) else [result["authors"]]
        text += f"**Authors**: {', '.join(authors)}\n"
    if result.get("affiliation"): text += f"**Affiliation**: {result['affiliation']}\n"
    if result.get("year"): text += f"**Year**: {result['year']}\n"
    if result.get("venue"): text += f"**Publication**: {result['venue']}\n"
    if result.get("doi"): text += f"**DOI**: {result['doi']}\n"
    if result.get("keywords"):
        kws = result["keywords"] if isinstance(result["keywords"], list) else [result["keywords"]]
        text += f"**Keywords**: {', '.join(kws)}\n"
    if result.get("volume"): text += f"**Volume**: {result['volume']}\n"
    if result.get("pages"): text += f"**Pages**: {result['pages']}\n"
    if result.get("issn"): text += f"**ISSN**: {result['issn']}\n"
    if result.get("pubDate"): text += f"**Published**: {result['pubDate']}\n"
    if result.get("pdfUrl"):
        text += f"**PDF**: {result['pdfUrl']}\n"
        hint_title = title.replace('"', "'")
        text += f"**Download**: use {db}_download(url=\"{result['pdfUrl']}\", title=\"{hint_title}\")\n"
    if result.get("citation"): text += f"\n**Citation**\n{result['citation']}\n"
    return [TextContent(type="text", text=text or "No details extracted.")]


# ══════════════════════════════════════════════════════════════════════
# Download Helpers
# ══════════════════════════════════════════════════════════════════════

async def _resolve_pdf_url(db: str, page, url: str, title: str):
    """Resolve URL to a direct PDF link. Returns (pdf_url, title, error_or_None)."""
    if any(kw in url for kw in ["stamp.jsp", "/pdf/", "getPDF.jsp", "pdfft"]):
        return url, title, None

    adapter = await get_adapter(db, page)
    detail_result = await adapter.detail(url)
    if detail_result.get("error") == "captcha":
        return url, title, "captcha"
    if detail_result.get("pdfUrl"):
        url = detail_result["pdfUrl"]
    if not title and detail_result.get("title"):
        title = detail_result["title"]
    return url, title, None


def _ieee_pdf_url(url: str) -> str:
    """Convert IEEE document/stamp URLs to getPDF.jsp endpoint."""
    if "/document/" in url and "getPDF" not in url:
        m = re.search(r'/document/(\d+)', url)
        if m:
            return f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}"
    if "stamp.jsp" in url:
        arnumber = url.split("arnumber=")[-1] if "arnumber=" in url else ""
        if arnumber:
            return f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"
    return url


CHALLENGE_GRACE_SECONDS = 15   # how long a download waits for Cloudflare before asking the user

# Fetch a URL (null = the current page) inside the page, so the browser's cookies apply,
# and return the body as base64. FileReader does the encoding natively; building a
# binary string byte by byte took seconds for large PDFs.
_FETCH_AS_BASE64_JS = """
    async (targetUrl) => {
        try {
            const resp = await fetch(targetUrl || window.location.href);
            if (!resp.ok) return 'HTTP ' + resp.status;
            const blob = await resp.blob();
            return await new Promise(resolve => {
                const fr = new FileReader();
                fr.onload = () => resolve(String(fr.result).split(',', 2)[1] || '');
                fr.onerror = () => resolve('ERROR:' + fr.error);
                fr.readAsDataURL(blob);
            });
        } catch (e) {
            return 'ERROR:' + e.message;
        }
    }
"""


async def _sd_navigate_and_fetch(page, url: str) -> str | None:
    """Navigate to ScienceDirect PDF URL, handle Cloudflare, return base64 or None.

    Cloudflare verification can destroy the execution context. After user completes
    the challenge manually, the page reloads — we wait and retry evaluate.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    for _ in range(80):   # up to 20 s for the redirect to the PDF host
        if "sciencedirectassets" in page.url:
            break
        await asyncio.sleep(0.25)

    # Give Cloudflare a short grace period; if it still blocks, hand over to the user
    # (ACTION_REQUIRED) instead of holding the tool call for minutes.
    deadline = time.monotonic() + CHALLENGE_GRACE_SECONDS
    challenged = False
    while True:
        try:
            page_text = await page.evaluate("() => document.body?.innerText?.slice(0, 500) || ''")
        except Exception:
            page_text = "just a moment"   # context destroyed mid-challenge; keep waiting
        if not is_challenge(page_text):
            break
        challenged = True
        if time.monotonic() > deadline:
            return None
        await asyncio.sleep(1)

    if challenged:
        await asyncio.sleep(2)   # let the page settle after the challenge passed

    # Retry evaluate with resilience to context destruction
    for retry in range(3):
        try:
            return await page.evaluate(_FETCH_AS_BASE64_JS, None)
        except Exception as e:
            if retry < 2:
                log.debug(f"SD fetch retry {retry+1}: {e}")
                await asyncio.sleep(2)
            else:
                log.info(f"SD fetch failed after retries: {e}")
                return None


def _save_pdf(pdf_data: bytes, title: str) -> Path:
    """Save PDF bytes to downloads directory without overwriting existing files."""
    downloads_dir = Path(os.getcwd()) / "downloads"
    downloads_dir.mkdir(exist_ok=True)
    save_path = _unique_path(downloads_dir, title, ".pdf")
    save_path.write_bytes(pdf_data)
    return save_path


def _unique_path(directory: Path, title: str, ext: str) -> Path:
    """directory/<title><ext>; adds ' (2)', ' (3)'… instead of overwriting."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip().rstrip('.')[:80]
    stem = stem or f"paper_{int(time.time())}"
    path = directory / f"{stem}{ext}"
    n = 2
    while path.exists():
        path = directory / f"{stem} ({n}){ext}"
        n += 1
    return path


def _looks_like_html(head: bytes) -> bool:
    h = head.lstrip()[:200].lower()
    return h.startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<body")) or b"<html" in h


async def _browser_download(browser, click, save_dir: Path,
                            start_timeout: float = 20, finish_timeout: float = 180):
    """Let the browser itself save a download into save_dir.

    Over connect_over_cdp, Playwright's download.save_as() tends to produce empty
    files. Instead, a browser-level CDP session sets Browser.setDownloadBehavior so
    the browser writes save_dir/<guid>, and Browser.downloadProgress says exactly
    when that download completed. Being browser-level, it also sees downloads CNKI
    starts in a new tab. `click` is an async callable that starts the download.
    Returns (path, suggested_filename, error_or_None)."""
    cdp = await browser.new_browser_cdp_session()
    loop = asyncio.get_running_loop()
    began, finished = loop.create_future(), loop.create_future()
    guid: dict = {}

    def on_begin(evt):
        if not began.done():
            guid["value"] = evt["guid"]
            began.set_result(evt)

    def on_progress(evt):
        if (evt.get("guid") == guid.get("value") and evt.get("state") in ("completed", "canceled")
                and not finished.done()):
            finished.set_result(evt["state"])

    cdp.on("Browser.downloadWillBegin", on_begin)
    cdp.on("Browser.downloadProgress", on_progress)
    try:
        await cdp.send("Browser.setDownloadBehavior", {
            "behavior": "allowAndName",
            "downloadPath": str(save_dir.resolve()),
            "eventsEnabled": True,
        })
        await click()
        try:
            evt = await asyncio.wait_for(began, start_timeout)
        except asyncio.TimeoutError:
            return None, "", "下载没有开始（可能需要登录或完成验证）"
        try:
            state = await asyncio.wait_for(finished, finish_timeout)
        except asyncio.TimeoutError:
            try:
                await cdp.send("Browser.cancelDownload", {"guid": evt["guid"]})
            except Exception:
                pass
            return None, "", f"下载超过 {finish_timeout:.0f} 秒仍未完成"
        if state != "completed":
            return None, "", "下载被取消"
        return save_dir / evt["guid"], evt.get("suggestedFilename", ""), None
    finally:
        try:   # hand downloads back to the browser's normal behavior
            await cdp.send("Browser.setDownloadBehavior", {"behavior": "default"})
        except Exception:
            pass
        try:
            await cdp.detach()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
# Download Handler (IEEE / ScienceDirect)
# ══════════════════════════════════════════════════════════════════════

async def handle_download(db: str, args: dict) -> list[TextContent]:
    """Download PDF from IEEE or ScienceDirect."""
    page, err = await _ensure_logged_in(db)
    if err or not page:
        return err or _need_login_response(db)

    url = args["url"]
    title = args.get("title", "")

    url, title, resolve_err = await _resolve_pdf_url(db, page, url, title)
    if resolve_err == "captcha":
        return _need_action_response(db, "详情页显示了验证页面。")

    if db == "ieee":
        url = _ieee_pdf_url(url)

    is_sd = "sciencedirect" in url or "sciencedirectassets" in page.url
    if is_sd and "/pdfft" in url:
        pdf_b64 = await _sd_navigate_and_fetch(page, url)
        if pdf_b64 is None:
            return _need_action_response(db, "PDF 域名显示了安全验证页面（Cloudflare / Security verification），请在浏览器中完成验证后重试下载。")
    else:
        try:
            await page.unroute("**/*")
        except Exception:
            pass
        pdf_b64 = await page.evaluate(_FETCH_AS_BASE64_JS, url)

    if not pdf_b64 or pdf_b64.startswith('ERROR:') or pdf_b64.startswith('HTTP '):
        await page.goto(
            url.replace('getPDF.jsp', 'stamp.jsp'),
            wait_until="domcontentloaded", timeout=45000,
        )
        return [TextContent(type="text",
            text=f"自动下载失败 ({pdf_b64[:80] if pdf_b64 else 'empty'})。已在浏览器中打开。\n"
                 f"URL: {page.url[:200]}")]

    pdf_data = base64.b64decode(pdf_b64)
    if pdf_data[:4] != b'%PDF':
        snippet = pdf_data[:200].decode('utf-8', errors='replace')
        await page.goto(
            url.replace('getPDF.jsp', 'stamp.jsp'),
            wait_until="domcontentloaded", timeout=45000,
        )
        return [TextContent(type="text",
            text=f"下载失败：返回内容不是 PDF（可能登录过期）。\n"
                 f"已在浏览器中打开。\nFirst bytes: {snippet[:100]}")]

    save_path = _save_pdf(pdf_data, title)
    return [TextContent(type="text",
        text=f"Downloaded PDF ({len(pdf_data)} bytes)\nSaved: {save_path}")]


# ══════════════════════════════════════════════════════════════════════
# Generic Handlers
# ══════════════════════════════════════════════════════════════════════

async def handle_status() -> list[TextContent]:
    lines = [f"**Registered databases**: {DB_LIST}"]
    for name in list_dbs():
        db = get_db(name)
        if not db:
            continue
        marker = " ← 已打开页面" if name in _pages else ""
        lines.append(f"  - `{name}`: {db['label']}{marker}")

    if _auth and _auth.is_alive():
        lines.append("\nCDP 连接: 已连接")
        for db_name, pg in _pages.items():
            lines.append(f"  {db_name}: {pg.url[:80] if _page_alive(pg) else '(页面已关闭)'}")
    else:
        lines.append("\nCDP 连接: 未连接。使用 {db}_login 工具连接。")

    return [TextContent(type="text", text="\n".join(lines))]


async def handle_logout() -> list[TextContent]:
    global _auth, _pages
    for pg in _pages.values():
        if _page_alive(pg):
            try:
                await pg.close()
            except Exception as e:
                log.debug(f"Closing tool tab: {e}")
    if _auth:
        try:
            await _auth.stop()
        except Exception as e:
            log.debug(f"Logout cleanup: {e}")
    _auth = None
    _pages = {}
    return [TextContent(type="text", text="已断开 CDP 连接并关闭了工具打开的标签页。浏览器和登录状态保持不变。")]


# ══════════════════════════════════════════════════════════════════════
# CNKI Handlers
# ══════════════════════════════════════════════════════════════════════

async def handle_cnki_search(args: dict) -> list[TextContent]:
    page, err = await _ensure_page("cnki")
    if err or not page:
        return [TextContent(type="text", text=err or "Failed to get CNKI page")]

    adapter = CnkiAdapter(page)
    result = await adapter.search(
        args["query"],
        author=args.get("author"),
        journal=args.get("journal"),
        year_start=args.get("year_start"),
        year_end=args.get("year_end"),
        page=args.get("page", 1),
        sort=args.get("sort"),
    )

    if not result.get("success"):
        err_msg = result.get("error", "unknown")
        if err_msg == "captcha":
            return _need_action_response("cnki", "正在显示滑块验证码。")
        return [TextContent(type="text", text=f"CNKI search failed: {err_msg}")]

    papers = result.get("papers", [])
    total = result.get("total", "?")
    page_info = result.get("page", "1/1")

    # 构建标题，显示实际使用的筛选条件
    filters = []
    if args.get("author"):    filters.append(f"作者={args['author']}")
    if args.get("journal"):   filters.append(f"期刊={args['journal']}")
    if args.get("year_start") or args.get("year_end"):
        filters.append(f"年份={args.get('year_start','?')}-{args.get('year_end','?')}")
    filter_str = f" [{', '.join(filters)}]" if filters else ""
    text = f"CNKI 搜索 \"{args['query']}\"{filter_str}：共 {total} 条结果 (第 {page_info} 页)\n\n"
    for i, p in enumerate(papers):
        text += f"[{i+1}] **{p.get('title', '?')}**\n"
        if p.get("authors"): text += f"    作者: {p['authors']}\n"
        if p.get("journal"): text += f"    期刊: {p['journal']}\n"
        if p.get("date"): text += f"    日期: {p['date']}\n"
        if p.get("citations"): text += f"    引用: {p['citations']}\n"
        if p.get("url"): text += f"    URL: {p['url']}\n"
        text += "\n"
    text += "→ 使用 cnki_detail(url=URL) 获取论文详情"
    return [TextContent(type="text", text=text)]


async def handle_cnki_detail(args: dict) -> list[TextContent]:
    page, err = await _ensure_page("cnki")
    if err or not page:
        return [TextContent(type="text", text=err or "Failed to get CNKI page")]

    adapter = CnkiAdapter(page)
    result = await adapter.detail(args["url"])

    if not result.get("success"):
        err_msg = result.get("error", "unknown")
        if err_msg == "captcha":
            return _need_action_response("cnki", "验证码。")
        return [TextContent(type="text", text=f"CNKI detail failed: {err_msg}")]

    text = ""
    if result.get("title"): text += f"**{result['title']}**\n\n"
    if result.get("authors"): text += f"**作者**: {', '.join(result['authors'])}\n"
    if result.get("affiliations"): text += f"**单位**: {', '.join(result['affiliations'])}\n"
    if result.get("journal"): text += f"**期刊**: {result['journal']}\n"
    if result.get("pubInfo"): text += f"**出版信息**: {result['pubInfo']}\n"
    if result.get("doi"): text += f"**DOI**: {result['doi']}\n"
    if result.get("abstract"): text += f"\n**摘要**\n{result['abstract']}\n"
    if result.get("keywords"): text += f"\n**关键词**: {', '.join(result['keywords'])}\n"
    if result.get("fund"): text += f"**基金**: {result['fund']}\n"
    if result.get("classification"): text += f"**分类号**: {result['classification']}\n"
    if result.get("isOnlineFirst"): text += "**状态**: 网络首发\n"
    return [TextContent(type="text", text=text or "未提取到详情")]


_CNKI_TITLE_JS = (
    "() => (document.querySelector('.brief h1')?.innerText || '')"
    "  .replace(/\\s*附视频\\s*$/, '').replace(/\\s*网络首发\\s*$/, '').trim()"
)
_CNKI_DOWNLOAD_LINKS = ("#pdfDown, .btn-dlpdf a", "#cajDown, .btn-dlcaj a")   # PDF preferred


async def handle_cnki_download(args: dict) -> list[TextContent]:
    """CNKI download: PDF if offered, otherwise CAJ. The browser saves the file
    itself (see _browser_download) and it is then renamed to the paper title."""
    page, err = await _ensure_page("cnki")
    if err or not page:
        return [TextContent(type="text", text=err or "Failed to get CNKI page")]

    url = args["url"]
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    try:
        await page.wait_for_selector('.brief h1', timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(1)

    page_text = await page.evaluate("() => document.body.innerText.slice(0, 3000)")
    if "机构登录" in page_text or "校外访问" in page_text:
        return _need_login_response("cnki")

    captcha = await page.evaluate("""() => {
        const el = document.querySelector('#tcaptcha_transform_dy');
        return el && el.getBoundingClientRect().top >= 0;
    }""")
    if captcha:
        return _need_action_response("cnki", "正在显示滑块验证码。")

    for selector in _CNKI_DOWNLOAD_LINKS:
        link = page.locator(selector).first
        if await link.count() > 0:
            break
    else:
        return [TextContent(type="text", text="未找到 PDF 或 CAJ 下载链接。")]

    title = await page.evaluate(_CNKI_TITLE_JS)
    save_dir = Path(os.getcwd()) / "downloads"
    save_dir.mkdir(exist_ok=True)

    path, suggested, err = await _browser_download(_auth.browser, link.click, save_dir)
    if err:
        return [TextContent(type="text",
            text=f"⚠️ CNKI 下载失败：{err}\n\n"
                 f"[ACTION_REQUIRED: 请使用 AskUserQuestion 询问用户是否已登录 CNKI 或完成验证]")]

    head = path.read_bytes()[:512]
    if not head or _looks_like_html(head):
        preview = head[:100].decode("utf-8", errors="replace")
        path.unlink(missing_ok=True)
        return [TextContent(type="text",
            text=f"CNKI 下载失败：返回的不是有效的 PDF/CAJ 文件（可能登录已过期）。\n内容预览: {preview}\n\n"
                 f"[ACTION_REQUIRED: 请使用 AskUserQuestion 询问用户是否已登录 CNKI]")]

    ext = ".pdf" if head.startswith(b"%PDF") else (Path(suggested).suffix.lower() or ".caj")
    final = _unique_path(save_dir, title or Path(suggested).stem, ext)
    path.rename(final)
    kind = ext.lstrip(".").upper()
    return [TextContent(type="text",
        text=f"CNKI {kind} 下载成功：{final.name}\n大小: {final.stat().st_size} bytes\n保存: {final}")]


# ══════════════════════════════════════════════════════════════════════
# MCP Server Entry
# ══════════════════════════════════════════════════════════════════════

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
