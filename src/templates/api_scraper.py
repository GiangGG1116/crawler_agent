"""TPL-003 — API-based scraper using httpx + JSON parsing.

For: REST API endpoints that return structured JSON data.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urljoin, urlencode, parse_qs, urlparse

from src.models.request import CrawlRequest, WebType
from src.templates.base_template import BaseTemplate, TemplateConfig
from src.utils.http_client import CrawlerHttpClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIScraper(BaseTemplate):
    """TPL-003: REST API scraper using HTTP requests + JSON parsing."""

    template_id = "TPL-003"
    template_name = "api_json_scraper"
    web_type = WebType.API_BASED
    tool_stack = ["httpx", "json"]

    def __init__(self, config: TemplateConfig | None = None):
        super().__init__(config)
        self.http_client = CrawlerHttpClient()
        self._next_url: Optional[str] = None
        self._current_offset: int = 0
        self._page_size: int = 50

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        """Configure API-specific settings."""
        if config.rate_limit:
            self.http_client.rate_limiter.rps = config.rate_limit.requests_per_second

        # Extract API pagination settings from config
        api_settings = config.selectors.get("api", {})
        self._page_size = api_settings.get("page_size", 50)
        self._data_path = api_settings.get("data_path", "data")  # JSON path to records array
        self._next_url_path = api_settings.get("next_url_path", "next")  # Path to next page URL
        self._total_path = api_settings.get("total_path", "total")  # Path to total count

    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        """Fetch API endpoint and extract records from JSON response."""
        headers = {**config.headers, "Accept": "application/json"}

        response = await self.http_client.fetch(url, headers=headers)

        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from {url}")
            return []

        # Extract records from nested JSON path
        records = self._extract_from_path(data, self._data_path)

        # Check for next page URL
        self._next_url = self._extract_from_path(data, self._next_url_path)
        if isinstance(self._next_url, list):
            self._next_url = None

        # Map fields according to config
        field_selectors = config.get_field_selectors()
        if field_selectors:
            records = [self._map_fields(record, field_selectors) for record in records]

        return records

    def _extract_from_path(self, data: Any, path: str) -> Any:
        """Extract value from nested dict using dot-notation path."""
        if not path:
            return data

        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                current = current[idx] if idx < len(current) else None
            else:
                return None
            if current is None:
                return None
        return current

    def _map_fields(self, record: dict[str, Any], field_selectors: dict) -> dict[str, Any]:
        """Map API response fields to output field names."""
        mapped: dict[str, Any] = {}
        for field_name, selector in field_selectors.items():
            # selector.selector contains the JSON path within each record
            value = self._extract_from_path(record, selector.selector)
            mapped[field_name] = value
        return mapped

    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        """Get next API page URL."""
        pagination = config.pagination

        # If API returned a next URL, use it
        if self._next_url and isinstance(self._next_url, str):
            return self._next_url

        # Offset-based pagination
        if pagination.type == "page_number" and pagination.url_pattern:
            self._current_offset += self._page_size
            pattern = pagination.url_pattern
            if "{offset}" in pattern:
                return urljoin(current_url, pattern.replace("{offset}", str(self._current_offset)))
            elif "{n}" in pattern:
                next_page = self._pages_crawled + 1
                return urljoin(current_url, pattern.replace("{n}", str(next_page)))

        # Query parameter pagination
        parsed = urlparse(current_url)
        params = parse_qs(parsed.query)

        if "page" in params:
            current_page = int(params["page"][0])
            params["page"] = [str(current_page + 1)]
            new_query = urlencode(params, doseq=True)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"

        if "offset" in params:
            current_offset = int(params["offset"][0])
            params["offset"] = [str(current_offset + self._page_size)]
            new_query = urlencode(params, doseq=True)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"

        return None
