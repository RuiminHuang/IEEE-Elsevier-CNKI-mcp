"""
ScienceDirect (Elsevier) database adapter.
"""

import asyncio
from urllib.parse import quote
from .base import BaseAdapter, year_range


class ScienceDirectAdapter(BaseAdapter):
    name = "sciencedirect"
    home_url = "https://www.sciencedirect.com/"

    PAGE_SIZE = 25

    @classmethod
    def build_search_url(cls, query: str, page: int = 1, year_start=None, year_end=None) -> str:
        offset = (int(page) - 1) * cls.PAGE_SIZE
        url = f"https://www.sciencedirect.com/search?qs={quote(query)}&show={cls.PAGE_SIZE}"
        years = year_range(year_start, year_end)
        return url + (f"&offset={offset}" if offset else "") + (f"&date={years[0]}-{years[1]}" if years else "")

    async def search(self, query: str, **kwargs) -> dict:
        search_url = self.build_search_url(query, int(kwargs.get("page") or 1),
                                           kwargs.get("year_start"), kwargs.get("year_end"))
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

        # One entry per li.ResultItem, in page order (structure: tests/fixtures/sd_search_items.html).
        # Fields are read from their own elements: textContent of a whole item glues words
        # together ("2022Weiping"), which broke both author splitting and year matching.
        result = await self.page.evaluate(r"""
            () => {
                const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                const papers = [];
                for (const li of document.querySelectorAll('li.ResultItem')) {
                    const a = li.querySelector('a.result-list-title-link');
                    if (!a) continue;
                    const names = Array.from(li.querySelectorAll('.Authors .author'))
                        .map(e => norm(e.textContent)).filter(Boolean);
                    const date = norm(li.querySelector('.srctitle-date-fields')?.textContent);
                    const pdfA = li.querySelector('a.download-link, a[href*="/pdfft"]');
                    papers.push({
                        title: norm(a.textContent), url: a.href,
                        pii: (a.href.match(/\/pii\/([A-Z0-9]+)/) || [])[1] || '',
                        authors: names.join('; '),
                        year: (date.match(/(?<!\d)(19|20)\d{2}(?!\d)/) || [''])[0],
                        source: norm(li.querySelector('.subtype-srctitle-link')?.textContent),
                        abstract: '',
                        pdfUrl: pdfA ? pdfA.href : '',
                        hasPdf: !!pdfA,
                    });
                }
                const total = norm(document.querySelector('.search-body-results-text')?.textContent)
                    || norm(document.body?.innerText).match(/([\d,]+)\s*results?/i)?.[0] || '';
                return { success: true, total: (total.match(/[\d,]+/) || [String(papers.length)])[0], papers };
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

        # Bibliographic fields come from the page's citation_* <meta> tags; authors, abstract,
        # keywords and the PDF button from the DOM (structure: tests/fixtures/sd_article.html).
        data = await self.page.evaluate(r"""
            () => {
                const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                const meta = name => norm(document.querySelector(`meta[name="${name}"]`)?.content);

                const title = meta('citation_title') || norm(document.querySelector('h1 .title-text, h1')?.textContent);
                // given name + surname only; skips affiliation letters like <sup>a</sup>
                const authors = Array.from(document.querySelectorAll('#author-group .react-xocs-alternative-link'))
                    .map(e => norm(e.textContent)).filter(Boolean);
                // #abstracts holds "Highlights" first, then the real abstract
                const absEl = document.querySelector('#abstracts > .abstract.author:not(.author-highlights)');
                const abstract = norm(absEl?.textContent).replace(/^Abstract\s*/i, '');
                const keywords = Array.from(document.querySelectorAll('.keywords-section .keyword'))
                    .map(k => norm(k.textContent)).filter(Boolean);
                const date = meta('citation_publication_date') || meta('citation_online_date');

                // the article's own "View PDF" button (not the references' PDF links); it renders
                // late, so fall back to the pii-based pdfft URL
                const pdfLink = document.querySelector('a.accessbar-utility-link[href*="pdfft"]');
                const pii = (location.href.match(/\/pii\/([A-Z0-9]+)/) || [])[1] || '';
                const pdfUrl = pdfLink ? pdfLink.href
                    : (pii ? location.origin + '/science/article/pii/' + pii + '/pdfft?isDTMRedir=true&download=true' : '');

                return {
                    title, authors, abstract, keywords, pdfUrl, url: location.href,
                    doi: meta('citation_doi'),
                    venue: meta('citation_journal_title') || norm(document.querySelector('.publication-title')?.textContent),
                    year: (date.match(/(19|20)\d{2}/) || [''])[0],
                    volume: meta('citation_volume'),
                    issn: meta('citation_issn'),
                    pubDate: date,
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
