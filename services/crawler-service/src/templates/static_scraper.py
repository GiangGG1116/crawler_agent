"""Static Scraper — template for scraping static HTML pages.

Uses httpx + BeautifulSoup for simple static sites.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from bs4 import BeautifulSoup
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class StaticScraper:
    """Generic static HTML scraper template."""

    template_id = "static_generic"

    def can_handle(self, url: str, data_type: str) -> bool:
        """This template can handle any URL as a fallback."""
        return True

    async def scrape(
        self,
        url: str,
        max_pages: int = 10,
        rate_limit_rps: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Scrape static HTML pages.

        Extracts article-like content from <article>, .post, .card elements.
        """
        records: list[dict[str, Any]] = []
        delay = 1.0 / rate_limit_rps

        async with httpx.AsyncClient(timeout=30) as client:
            for page in range(1, max_pages + 1):
                try:
                    logger.info("Crawling page %d: %s", page, url)
                    resp = await client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    html = resp.text

                    soup = BeautifulSoup(html, "lxml")

                    # Extract items from common containers
                    items = (
                        soup.select("article")
                        or soup.select(".post")
                        or soup.select(".card")
                        or soup.select(".item")
                    )

                    for item in items:
                        record = self._extract_record(item)
                        if record:
                            records.append(record)

                    # Try to find next page
                    next_link = soup.select_one(
                        "a[rel='next'], .next a, a:contains('Next')"
                    )
                    if not next_link or not next_link.get("href"):
                        break

                    # Resolve relative URLs
                    from urllib.parse import urljoin

                    url = urljoin(url, next_link["href"])

                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error("Error on page %d: %s", page, e)
                    break

        logger.info("Scraped %d records from %s", len(records), url)
        return records

    def _extract_record(self, item) -> dict[str, Any] | None:
        """Extract a structured record from an HTML element."""
        title_el = item.select_one("h1, h2, h3, .title, [class*='title']")
        link_el = item.select_one("a[href]")
        desc_el = item.select_one("p, .description, .summary, [class*='desc']")
        date_el = item.select_one("time, .date, [class*='date'], [datetime]")
        img_el = item.select_one("img[src]")

        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            return None

        return {
            "title": title,
            "url": link_el.get("href", "") if link_el else "",
            "description": desc_el.get_text(strip=True) if desc_el else "",
            "date": (
                (date_el.get("datetime") or date_el.get_text(strip=True))
                if date_el
                else ""
            ),
            "image": img_el.get("src", "") if img_el else "",
        }
