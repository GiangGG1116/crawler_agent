"""CrawlService — business logic for Phase 0 and Phase 1.

Phase 0: Analyze target site (web type, selectors, pagination, anti-bot)
Phase 1: Execute template-based crawl using registered templates
"""

from __future__ import annotations

from typing import Any

from shared.models.request import CrawlRequest
from shared.utils.config import get_settings
from shared.utils.logger import get_logger
from src.models import CrawlerResponse, TemplateFailure

logger = get_logger(__name__)


class CrawlService:
    """Orchestrates site analysis and template crawling."""

    def __init__(self):
        self._settings = get_settings()

    async def analyze(self, url: str, data_type: str) -> dict[str, Any]:
        """Phase 0: Analyze target site structure.

        Detects web type (STATIC/DYNAMIC/API_BASED/PAGINATED),
        content selectors, pagination patterns, and anti-bot measures.
        """
        logger.info("Analyzing site: %s", url)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, follow_redirects=True)
                html = resp.text
                content_type = resp.headers.get("content-type", "")

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # Detect web type
            web_type = self._detect_web_type(soup, html, content_type)

            # Detect selectors
            selectors = self._detect_selectors(soup, data_type)

            # Detect pagination
            pagination = self._detect_pagination(soup)

            # Check robots.txt
            from shared.utils.robots import check_robots_txt

            robots_allowed = await check_robots_txt(url)

            analysis = {
                "url": url,
                "web_type": web_type,
                "selectors": selectors,
                "pagination": pagination,
                "robots_allowed": robots_allowed,
                "content_length": len(html),
                "title": soup.title.string if soup.title else None,
                "recommendation": {
                    "tool": (
                        "playwright"
                        if web_type in ("DYNAMIC", "PAGINATED")
                        else "httpx"
                    ),
                    "challenges": [],
                },
            }

            logger.info("Analysis complete for %s: web_type=%s", url, web_type)
            return analysis

        except Exception as e:
            logger.error("Analysis failed for %s: %s", url, e)
            return {
                "url": url,
                "web_type": "UNKNOWN",
                "error": str(e),
                "recommendation": {"tool": "playwright", "challenges": [str(e)]},
            }

    async def execute(self, request: CrawlRequest) -> CrawlerResponse:
        """Phase 1: Execute template-based crawl."""
        logger.info("Executing crawl for: %s", request.target.url)

        from src.templates.registry import TemplateRegistry

        registry = TemplateRegistry()

        # Try matching templates
        template = registry.match(request.target.url, request.data_spec.data_type.value)

        if not template:
            logger.info("No template match for %s, returning empty", request.target.url)
            return CrawlerResponse(
                status="no_template",
                errors=["No matching template found for this URL pattern"],
            )

        try:
            records = await template.scrape(
                url=request.target.url,
                max_pages=request.scope.max_pages,
                rate_limit_rps=request.constraints.rate_limit_rps,
            )

            # Validate records
            from src.processing.validator import SchemaValidator

            validator = SchemaValidator()
            valid_records = validator.validate_records(
                records,
                request.data_spec.required_fields,
            )

            return CrawlerResponse(
                status="success",
                records=valid_records,
                record_count=len(valid_records),
                template_id=template.template_id,
            )

        except Exception as e:
            logger.error("Template crawl failed: %s", e)
            return CrawlerResponse(
                status="failed",
                errors=[str(e)],
                failures=[
                    TemplateFailure(
                        template_id=template.template_id if template else None,
                        reason=str(e),
                    )
                ],
            )

    def _detect_web_type(self, soup, html: str, content_type: str) -> str:
        """Detect if site is STATIC, DYNAMIC, API_BASED, or PAGINATED."""
        # Check for SPA frameworks
        scripts = soup.find_all("script")
        script_texts = " ".join(s.get("src", "") for s in scripts if s.get("src"))

        if any(
            fw in script_texts.lower() for fw in ["react", "vue", "angular", "next"]
        ):
            return "DYNAMIC"

        if "application/json" in content_type:
            return "API_BASED"

        # Check for pagination
        pagination_selectors = soup.select(
            ".pagination, .pager, nav[aria-label*='page'], [class*='pagina']"
        )
        if pagination_selectors:
            return "PAGINATED"

        # Check for heavy JS reliance
        noscript = soup.find("noscript")
        if noscript and "enable javascript" in (noscript.get_text() or "").lower():
            return "DYNAMIC"

        return "STATIC"

    def _detect_selectors(self, soup, data_type: str) -> dict[str, list[str]]:
        """Detect candidate CSS selectors for data extraction."""
        selectors: dict[str, list[str]] = {"items": [], "fields": {}}

        # Common article/product containers
        container_patterns = [
            "article",
            ".article",
            ".post",
            ".card",
            ".item",
            ".product",
            ".listing",
            "[class*='article']",
            "[class*='post']",
        ]

        for pattern in container_patterns:
            elements = soup.select(pattern)
            if len(elements) >= 3:  # At least 3 items = likely a list
                selectors["items"].append(pattern)

        return selectors

    def _detect_pagination(self, soup) -> dict[str, Any]:
        """Detect pagination patterns."""
        pagination = {"type": "none", "selectors": []}

        # Check for next button
        next_link = soup.select_one(
            "a[rel='next'], .next, a:contains('Next'), [class*='next']"
        )
        if next_link:
            pagination["type"] = "link"
            pagination["selectors"].append(str(next_link.get("href", "")))

        # Check for numbered pages
        page_links = soup.select(".pagination a, .pager a")
        if page_links:
            pagination["type"] = "numbered"
            pagination["page_count"] = len(page_links)

        return pagination
