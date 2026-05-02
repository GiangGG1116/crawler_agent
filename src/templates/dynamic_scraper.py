"""TPL-002 — Dynamic page scraper using Playwright + BeautifulSoup.

For: SPAs, React/Vue apps — pages that require JavaScript rendering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.models.request import CrawlRequest, WebType
from src.templates.base_template import BaseTemplate, TemplateConfig, FieldSelector
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DynamicScraper(BaseTemplate):
    """TPL-002: Dynamic scraper using Playwright for JS rendering."""

    template_id = "TPL-002"
    template_name = "dynamic_spa_scraper"
    web_type = WebType.DYNAMIC
    tool_stack = ["playwright", "beautifulsoup4"]

    def __init__(self, config: TemplateConfig | None = None):
        super().__init__(config)
        self._browser = None
        self._context = None
        self._page = None

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        """Launch Playwright browser."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        self._page = await self._context.new_page()

        logger.info("Playwright browser launched", extra={"request_id": request.request_id})

    async def teardown(self) -> None:
        """Close browser resources."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()

    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        """Navigate to URL, wait for JS rendering, then extract data."""
        if not self._page:
            raise RuntimeError("Browser not initialized. Call setup() first.")

        await self._page.goto(url, wait_until="networkidle", timeout=60000)

        # Wait for content container to appear
        try:
            await self._page.wait_for_selector(config.container_selector, timeout=15000)
        except Exception:
            logger.warning(f"Container selector timeout: {config.container_selector}")

        # Optional: scroll to trigger lazy loading
        await self._scroll_page()

        # Get rendered HTML
        html = await self._page.content()
        soup = BeautifulSoup(html, "lxml")

        container = soup.select_one(config.container_selector)
        if not container:
            container = soup

        items = container.select(config.item_selector)
        field_selectors = config.get_field_selectors()

        records = []
        for item in items:
            record = self._extract_record(item, field_selectors, url)
            if record:
                records.append(record)

        return records

    def _extract_record(
        self, element: Any, field_selectors: dict[str, FieldSelector], page_url: str,
    ) -> dict[str, Any]:
        """Extract a single record from a DOM element."""
        record: dict[str, Any] = {}

        for field_name, selector in field_selectors.items():
            try:
                el = element.select_one(selector.selector)
                if el is None:
                    record[field_name] = None
                    continue

                if selector.attribute:
                    value = el.get(selector.attribute, "")
                elif selector.type == "html":
                    value = str(el)
                else:
                    value = el.get_text(strip=True)

                if selector.type == "url" and value:
                    value = urljoin(page_url, value)

                record[field_name] = value
            except Exception:
                record[field_name] = None

        return record

    async def _scroll_page(self, scroll_count: int = 3, delay_ms: int = 500) -> None:
        """Scroll page to trigger lazy loading of images/content."""
        if not self._page:
            return
        for _ in range(scroll_count):
            await self._page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(delay_ms / 1000)

    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        """Handle pagination for dynamic pages."""
        if not self._page:
            return None

        pagination = config.pagination

        if pagination.type == "infinite_scroll":
            # Scroll to bottom and check for new content
            prev_height = await self._page.evaluate("document.body.scrollHeight")
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            new_height = await self._page.evaluate("document.body.scrollHeight")
            if new_height > prev_height:
                return current_url  # Same URL, more content loaded
            return None

        elif pagination.type == "load_more" and pagination.selector:
            # Click "load more" button
            try:
                btn = self._page.locator(pagination.selector)
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1.5)
                    return current_url
            except Exception:
                pass
            return None

        elif pagination.type == "next_button" and pagination.selector:
            try:
                next_btn = self._page.locator(pagination.selector)
                if await next_btn.is_visible():
                    href = await next_btn.get_attribute("href")
                    if href:
                        return urljoin(current_url, href)
                    await next_btn.click()
                    await self._page.wait_for_load_state("networkidle")
                    return self._page.url
            except Exception:
                pass
            return None

        elif pagination.type == "page_number" and pagination.url_pattern:
            next_page = self._pages_crawled + 1
            pattern = pagination.url_pattern.replace("{n}", str(next_page))
            return urljoin(current_url, pattern)

        return None
