"""TPL-005 — Authenticated scraper using Playwright with login flow.

For: Login-required portals and protected content.
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


class AuthScraper(BaseTemplate):
    """TPL-005: Authenticated scraper with login automation."""

    template_id = "TPL-005"
    template_name = "authenticated_portal_scraper"
    web_type = WebType.AUTHENTICATED
    tool_stack = ["playwright", "beautifulsoup4"]

    def __init__(self, config: TemplateConfig | None = None):
        super().__init__(config)
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()

        # Perform login if auth config provided
        auth = request.constraints.auth_config
        if auth and auth.login_url:
            await self._login(auth)

    async def _login(self, auth) -> None:
        if not self._page:
            return
        logger.info(f"Logging in at {auth.login_url}")
        await self._page.goto(auth.login_url, wait_until="networkidle")

        if auth.username_selector and auth.username:
            await self._page.fill(auth.username_selector, auth.username)
        if auth.password_selector and auth.password:
            await self._page.fill(auth.password_selector, auth.password)
        if auth.submit_selector:
            await self._page.click(auth.submit_selector)
            await self._page.wait_for_load_state("networkidle")

        if auth.success_indicator:
            try:
                await self._page.wait_for_selector(auth.success_indicator, timeout=10000)
                self._logged_in = True
                logger.info("Login successful")
            except Exception:
                logger.error("Login failed — success indicator not found")
        else:
            self._logged_in = True

    async def teardown(self) -> None:
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()

    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        if not self._page:
            raise RuntimeError("Browser not initialized")

        await self._page.goto(url, wait_until="networkidle")
        html = await self._page.content()
        soup = BeautifulSoup(html, "lxml")

        container = soup.select_one(config.container_selector) or soup
        items = container.select(config.item_selector)
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
                        record[name] = el.get(sel.attribute, "")
                    else:
                        record[name] = el.get_text(strip=True)
                except Exception:
                    record[name] = None
            records.append(record)
        return records

    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        if not self._page:
            return None
        pagination = config.pagination
        if pagination.selector:
            try:
                btn = self._page.locator(pagination.selector)
                if await btn.is_visible():
                    href = await btn.get_attribute("href")
                    if href:
                        return urljoin(current_url, href)
            except Exception:
                pass
        return None
