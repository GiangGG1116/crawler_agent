"""Template Registry — manages available scraping templates.

Templates are matched by URL pattern and data type.
"""

from __future__ import annotations

from shared.utils.logger import get_logger
from src.templates.static_scraper import StaticScraper

logger = get_logger(__name__)


class TemplateRegistry:
    """Registry of available scraping templates."""

    def __init__(self):
        self._templates = [
            StaticScraper(),
        ]

    def match(self, url: str, data_type: str) -> StaticScraper | None:
        """Find the first template that matches the given URL and data type."""
        for template in self._templates:
            if template.can_handle(url, data_type):
                logger.info("Template match: %s for %s", template.template_id, url)
                return template

        logger.info("No template match for url=%s data_type=%s", url, data_type)
        return None
