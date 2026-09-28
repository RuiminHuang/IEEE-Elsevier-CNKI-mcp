"""
ScienceDirect (Elsevier) database adapter.
"""

import asyncio
from urllib.parse import quote
from .base import BaseAdapter


class ScienceDirectAdapter(BaseAdapter):
    name = "sciencedirect"
    home_url = "https://www.sciencedirect.com/"

    PAGE_SIZE = 25

    @classmethod
    def build_search_url(cls, query: str, page: int = 1) -> str:
        offset = (int(page) - 1) * cls.PAGE_SIZE
        url = f"https://www.sciencedirect.com/search?qs={quote(query)}&show={cls.PAGE_SIZE}"
        return url + (f"&offset={offset}" if offset else "")

    async def search(self, query: str, **kwargs) -> dict:
        search_url = self.build_search_url(query, int(kwargs.get("page") or 1))
        await self._navigate(search_url)
        await asyncio.sleep(4)

        # 检测 Cloudflare 验证码，等待用户手动完成
        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        # 等搜索结果加载（标题链接）
        try:
            await self.page.wait_for_selector(
                'a[href*="/science/article/pii/"]', timeout=20000
            )
            await asyncio.sleep(1)
        except Exception:
            # 可能验证码又出现了
            captcha_result = await self._check_and_notify_captcha()
            if captcha_result:
                return captcha_result
            return {"success": False, "error": "timeout — 搜索结果未加载，可能页面结构变化"}

        # Every result in page order; hasPdf marks the ones with a "View PDF" link.
        result = await self.page.evaluate(r"""
            () => {
                const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                const papers = [];
                const seen = new Set();
                for (const a of document.querySelectorAll('a[href*="/science/article/pii/"]')) {
                    const m = a.href.match(/\/pii\/([A-Z0-9]+)/);
                    if (!m || seen.has(m[1]) || /\/pdf/i.test(a.pathname)) continue;   // skip "View PDF" links
                    const title = norm(a.textContent);
                    if (title.length < 5) continue;
                    seen.add(m[1]);
                    const item = a.closest('li, article, [class*="result-item"], [class*="ResultItem"]') || a.parentElement;
                    const pdfA = item.querySelector('a.download-link, a[href*="/pdfft"], a[href*="pdf.sciencedirectassets"]');
                    papers.push({
                        title, url: a.href, pii: m[1],
                        authors: norm(item.querySelector('[class*="author" i]')?.textContent),
                        year: (item.textContent.match(/\b(19|20)\d{2}\b/) || [''])[0],
                        abstract: norm(item.querySelector('[class*="abstract"], [class*="snippet"]')?.textContent).slice(0, 300),
                        pdfUrl: pdfA ? pdfA.href : '',
                        hasPdf: !!pdfA,
                    });
                }
                const totalMatch = (document.body?.innerText || '').match(/([\d,]+)\s*[Rr]esult/);
                return { success: true, total: totalMatch ? totalMatch[1] : String(papers.length), papers };
            }
        """)

        return result

    async def detail(self, url: str, **kwargs) -> dict:
        await self._navigate(url)

        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        try:
            await self.page.wait_for_selector('h1', timeout=15000)
        except Exception:
            pass

        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        data = await self.page.evaluate("""
            () => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

                // 标题：去掉常见前缀
                let title = norm(
                    document.querySelector('h1')?.textContent
                    || document.querySelector('[class*="title"]')?.textContent
                );
                title = title.replace(/^(Research paper|Review article|Short communication|Editorial|Letter|Perspective|Case report|Technical note)\\s*/i, '');

                // 作者：从 content-authors 或 author-group 提取
                let authors = [];
                const authorEl = document.querySelector('.content-authors, .author-group');
                if (authorEl) {
                    let authorText = norm(authorEl.textContent || '');
                    // 去掉前缀 "Author links open overlay panel"
                    authorText = authorText.replace(/^Author links open overlay panel\\s*/i, '');
                    // 去掉 "Show more" 等后缀
                    authorText = authorText.replace(/Show m?o?r?e?.*$/i, '').trim();
                    // 按逗号分隔
                    authors = authorText.split(',').map(s => norm(s)).filter(t => t && t.length > 1);
                }

                const abstractEl = document.querySelector(
                    '#abstracts, [class*="abstract"], .abstract.author'
                );
                let abstract = norm(abstractEl?.textContent || '');
                abstract = abstract.replace(/^Abstract\\s*/i, '');

                const doiEl = document.querySelector('a[href*="doi.org"], [class*="doi"]');
                const doiText = doiEl?.href?.match(/doi\\.org\\/(.+)/)?.[1]
                    || norm(doiEl?.textContent);

                const keywords = Array.from(
                    document.querySelectorAll('[class*="keyword"] span, .keyword a')
                ).map(k => norm(k.textContent)).filter(t => t && t !== ';');

                const journal = norm(
                    document.querySelector('a[title*="source"], [class*="publication"], .publication-title-link')?.textContent
                );

                // 查找真正的 PDF 直链
                let pdfUrl = '';
                const pdfLink = document.querySelector(
                    'a.download-link, a[href*="pdf.sciencedirectassets"], a[href*="/pdfft"], a[data-test="pdf-link"]'
                );
                if (pdfLink) {
                    pdfUrl = pdfLink.href;
                }
                // 回退到 /pdfft 模式
                if (!pdfUrl) {
                    const piiMatch = location.href.match(/\\/pii\\/([A-Z0-9]+)/);
                    const pii = piiMatch ? piiMatch[1] : '';
                    if (pii) {
                        pdfUrl = location.origin + '/science/article/pii/' + pii
                            + '/pdfft?isDTMRedir=true&download=true';
                    }
                }

                return {
                    title, authors, abstract, doi: doiText || '',
                    keywords, journal, pdfUrl, url: location.href
                };
            }
        """)

        return {"success": True, **data}

    async def _check_bot_challenge(self) -> bool:
        """检测 Cloudflare bot 验证页面。"""
        try:
            text = await self.page.evaluate(
                "() => document.body?.innerText?.slice(0, 1000) || ''"
            )
            if "Are you a robot" in text:
                return True
            if "Just a moment" in text and ("challenge" in text.lower() or "checking" in text.lower()):
                return True
        except Exception:
            pass
        return False

    async def _check_and_notify_captcha(self) -> dict | None:
        """检测 Cloudflare 验证码，检测到立即返回错误（不等待）。返回 None 表示无验证码。"""
        if await self._check_bot_challenge():
            return {"success": False, "error": "captcha"}
        return None
