"""TPL-004 — Paginated scraper using httpx + BeautifulSoup.

For: E-commerce listings, search results — multi-page static content.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.models.request import CrawlRequest, WebType
from src.templates.base_template import BaseTemplate, TemplateConfig, FieldSelector
from src.utils.http_client import CrawlerHttpClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PaginatedScraper(BaseTemplate):
    """TPL-004: Multi-page scraper optimized for paginated listings."""

    template_id = "TPL-004"
    template_name = "paginated_listing_scraper"
    web_type = WebType.PAGINATED
    tool_stack = ["httpx", "beautifulsoup4"]

    def __init__(self, config: TemplateConfig | None = None):
        super().__init__(config)
        self.http_client = CrawlerHttpClient()
        self._visited_urls: set[str] = set()
        self._last_soup: Optional[BeautifulSoup] = None

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        if config.rate_limit:
            self.http_client.rate_limiter.rps = config.rate_limit.requests_per_second

    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        if url in self._visited_urls:
            return []
        self._visited_urls.add(url)

        response = await self.http_client.fetch(url)
        soup = BeautifulSoup(response.text, "lxml")
        self._last_soup = soup

        container = soup.select_one(config.container_selector) or soup
        items = container.select(config.item_selector)
        if not items:
            return []

        field_selectors = config.get_field_selectors()
        records = []
        for item in items:
            record: dict[str, Any] = {}
            for name, sel in field_selectors.items():
                try:
                    el = item.select_one(sel.selector)
                    if not el:
                        record[name] = None
                        continue
                    if sel.attribute:
                        val = el.get(sel.attribute, "")
                    else:
                        val = el.get_text(strip=True)
                    if sel.type == "url" and val:
                        val = urljoin(url, val)
                    record[name] = val
                except Exception:
                    record[name] = None
            if any(v is not None for v in record.values()):
                records.append(record)
        return records

    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        pagination = config.pagination
        if pagination.type == "page_number" and pagination.url_pattern:
            next_page = self._pages_crawled + 1
            url = urljoin(current_url, pagination.url_pattern.replace("{n}", str(next_page)))
            return url if url not in self._visited_urls else None
        if pagination.selector and self._last_soup:
            link = self._last_soup.select_one(pagination.selector)
            if link and link.get("href"):
                url = urljoin(current_url, link["href"])
                return url if url not in self._visited_urls else None
        return None
