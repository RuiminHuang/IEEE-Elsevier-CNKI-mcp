"""
Base class for database adapters.
"""

import re
from datetime import datetime

from playwright.async_api import Page


# Bot checks in page text: Cloudflare ("Just a moment", "Are you a robot") and Elsevier's
# own "Security verification" page on pdf.sciencedirectassets.com, whose body reads
# "Request Verification: In Progress".
CHALLENGE_MARKERS = ("are you a robot", "just a moment", "request verification")


def is_challenge(page_text: str) -> bool:
    text = (page_text or "").lower()
    return any(m in text for m in CHALLENGE_MARKERS)


def normalize_year(value) -> str:
    """'2020年' / 2020 / ' 2020 ' -> '2020'; empty when no year given."""
    return re.sub(r"\D", "", str(value or ""))[:4]


def year_range(year_start, year_end) -> tuple[str, str] | None:
    """Normalized (start, end) with open ends filled in, or None when no year was given."""
    start, end = normalize_year(year_start), normalize_year(year_end)
    if not (start or end):
        return None
    return start or "1800", end or str(datetime.now().year)


class BaseAdapter:
    name: str = "base"
    home_url: str = ""

    def __init__(self, page: Page):
        self.page = page

    async def search(self, query: str, **kwargs) -> dict:
        raise NotImplementedError

    async def detail(self, url: str, **kwargs) -> dict:
        raise NotImplementedError

    async def _navigate(self, url: str, timeout: int = 30000):
        """Go to url. Callers then wait for the element or response they actually need;
        waiting for "network idle" cost ~10 s per call on sites whose analytics never go idle."""
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
