"""
Base class for database adapters.
"""

import re
from datetime import datetime

from playwright.async_api import Page


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
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
