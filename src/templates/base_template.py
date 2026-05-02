"""Base template — abstract interface for all scraper templates.

Every template (TPL-001 through TPL-006) extends this class.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.models.request import CrawlRequest, WebType
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Template Configuration Schema (matches 3.1.2 in design doc)
# =============================================================================

class FieldSelector(BaseModel):
    """Selector definition for extracting a single field."""
    selector: str
    type: str = "text"  # text | html | date | url | number
    attribute: Optional[str] = None  # e.g., "href", "src", "datetime"
    transform: Optional[str] = None  # e.g., "parse_currency", "parse_date"


class PaginationConfig(BaseModel):
    """Pagination strategy configuration."""
    type: str = "next_button"  # next_button | page_number | load_more | infinite_scroll
    selector: Optional[str] = None
    url_pattern: Optional[str] = None  # e.g., "?page={n}"
    max_pages: int = 100


class RateLimitConfig(BaseModel):
    """Per-template rate limiting."""
    requests_per_second: float = 2.0
    delay_between_pages_ms: int = 1000


class TemplateConfig(BaseModel):
    """Full configuration for a scraper template."""
    template_id: str
    template_name: str
    web_type: WebType
    tool_stack: list[str] = Field(default_factory=list)
    selectors: dict[str, Any] = Field(default_factory=dict)  # container, item, fields
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    headers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_json_file(cls, path: Path) -> TemplateConfig:
        """Load template config from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def get_field_selectors(self) -> dict[str, FieldSelector]:
        """Parse field selectors from config."""
        fields = self.selectors.get("fields", {})
        return {name: FieldSelector(**spec) for name, spec in fields.items()}

    @property
    def container_selector(self) -> str:
        return self.selectors.get("container", "body")

    @property
    def item_selector(self) -> str:
        return self.selectors.get("item", "*")


# =============================================================================
# Abstract Base Template
# =============================================================================

class BaseTemplate(ABC):
    """
    Abstract base class for all scraper templates.

    Subclasses must implement:
    - scrape_page(): Extract records from a single page
    - handle_pagination(): Navigate to next page

    The base class provides:
    - run(): Full execution flow with pagination and rate limiting
    - extract_field(): Field extraction with type handling
    """

    template_id: str = ""
    template_name: str = ""
    web_type: WebType = WebType.STATIC
    tool_stack: list[str] = []

    def __init__(self, config: TemplateConfig | None = None):
        self.config = config
        self._records: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._pages_crawled = 0

    async def run(self, request: CrawlRequest, config: TemplateConfig | None = None) -> list[dict[str, Any]]:
        """
        Execute the template: scrape all pages according to scope.

        Returns:
            List of extracted records (raw data).
        """
        effective_config = config or self.config
        if not effective_config:
            raise ValueError(f"No config provided for template {self.template_id}")

        self._records = []
        self._errors = []
        self._pages_crawled = 0

        max_pages = min(
            request.scope.max_pages,
            effective_config.pagination.max_pages,
        )
        max_records = request.scope.max_records

        logger.info(
            f"Starting template {self.template_id}: max_pages={max_pages}, max_records={max_records}",
            extra={"request_id": request.request_id, "phase": "phase1", "template_id": self.template_id},
        )

        current_url = request.target.url

        try:
            await self.setup(request, effective_config)

            while self._pages_crawled < max_pages and len(self._records) < max_records:
                page_records = await self.scrape_page(current_url, effective_config)
                self._records.extend(page_records)
                self._pages_crawled += 1

                logger.debug(
                    f"Page {self._pages_crawled}: {len(page_records)} records (total: {len(self._records)})",
                    extra={"request_id": request.request_id, "template_id": self.template_id},
                )

                if request.scope.mode.value == "single_page":
                    break

                next_url = await self.handle_pagination(current_url, effective_config)
                if not next_url:
                    break
                current_url = next_url

        except Exception as e:
            self._errors.append(str(e))
            logger.error(
                f"Template {self.template_id} error: {e}",
                extra={"request_id": request.request_id, "template_id": self.template_id},
            )
        finally:
            await self.teardown()

        logger.info(
            f"Template {self.template_id} completed: {len(self._records)} records, {self._pages_crawled} pages, {len(self._errors)} errors",
            extra={"request_id": request.request_id, "template_id": self.template_id},
        )
        return self._records

    @abstractmethod
    async def scrape_page(self, url: str, config: TemplateConfig) -> list[dict[str, Any]]:
        """Extract records from a single page. Must be implemented by subclasses."""
        ...

    @abstractmethod
    async def handle_pagination(self, current_url: str, config: TemplateConfig) -> Optional[str]:
        """
        Get the next page URL.

        Returns:
            Next page URL or None if no more pages.
        """
        ...

    async def setup(self, request: CrawlRequest, config: TemplateConfig) -> None:
        """Optional setup hook (e.g., start browser, login)."""
        pass

    async def teardown(self) -> None:
        """Optional teardown hook (e.g., close browser)."""
        pass

    @property
    def errors(self) -> list[str]:
        return self._errors

    @property
    def pages_crawled(self) -> int:
        return self._pages_crawled
