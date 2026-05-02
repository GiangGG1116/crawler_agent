"""TPL-001 — Static page scraper using requests + BeautifulSoup.

For: Blog, wiki, news articles — plain HTML without JS rendering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.models.request import CrawlRequest, WebType
from src.templates.base_template import BaseTemplate, TemplateConfig, FieldSelector
from src.utils.http_client import CrawlerHttpClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StaticScraper(BaseTemplate):
    """TPL-001: Static HTML scraper using requests + BeautifulSoup4."""

    template_id = "TPL-001"
    template_name = "static_article_scraper"
    web_type = WebType.STATIC
    tool_stack = ["requests", "beautifulsoup4"]

    def __init__(self, config: TemplateConfig | None = None):
        super().__init__(config)
        self.http_client = CrawlerHttpClient()
        self._base_url: str = ""

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        self._base_url = request.target.url
        # Apply rate limit from config
        if config.rate_limit:
            self.http_client.rate_limiter.rps = config.rate_limit.requests_per_second

    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        """Fetch page and extract records using CSS selectors."""
        response = await self.http_client.fetch(url)
        soup = BeautifulSoup(response.text, "lxml")

        container = soup.select_one(config.container_selector)
        if not container:
            logger.warning(f"Container not found: {config.container_selector}")
            container = soup

        items = container.select(config.item_selector)
        if not items:
            logger.warning(f"No items found with selector: {config.item_selector}")
            return []

        field_selectors = config.get_field_selectors()
        records = []

        for item in items:
            record = self._extract_record(item, field_selectors, url)
            if record:
                records.append(record)

        return records

    def _extract_record(
        self,
        element: Any,
        field_selectors: dict[str, FieldSelector],
        page_url: str,
    ) -> dict[str, Any]:
        """Extract a single record from a DOM element."""
        record: dict[str, Any] = {}

        for field_name, selector in field_selectors.items():
            try:
                el = element.select_one(selector.selector)
                if el is None:
                    record[field_name] = None
                    continue

                value = self._extract_value(el, selector, page_url)
                record[field_name] = value
            except Exception as e:
                logger.debug(f"Field extraction failed: {field_name} → {e}")
                record[field_name] = None

        return record

    def _extract_value(self, element: Any, selector: FieldSelector, page_url: str) -> Any:
        """Extract value from element based on selector type."""
        if selector.attribute:
            raw = element.get(selector.attribute, "")
        elif selector.type == "html":
            raw = str(element)
        else:
            raw = element.get_text(strip=True)

        # Apply type transforms
        if selector.type == "url" and raw:
            raw = urljoin(page_url, raw)
        elif selector.transform == "parse_currency" and raw:
            import re
            numbers = re.findall(r"[\d,.]+", raw)
            if numbers:
                raw = float(numbers[0].replace(",", ""))
        elif selector.type == "date" and raw:
            from dateutil.parser import parse as parse_date
            try:
                raw = parse_date(raw).isoformat()
            except (ValueError, TypeError):
                pass

        return raw

    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        """Find and return the next page URL."""
        pagination = config.pagination

        if pagination.type == "page_number" and pagination.url_pattern:
            # URL pattern-based pagination: ?page={n}
            next_page = self._pages_crawled + 1
            pattern = pagination.url_pattern.replace("{n}", str(next_page))
            return urljoin(current_url, pattern)

        elif pagination.type == "next_button" and pagination.selector:
            # DOM-based: find next link
            response = await self.http_client.fetch(current_url)
            soup = BeautifulSoup(response.text, "lxml")
            next_link = soup.select_one(pagination.selector)
            if next_link and next_link.get("href"):
                return urljoin(current_url, next_link["href"])

        return None
