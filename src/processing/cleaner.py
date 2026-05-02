"""Data Cleaner — normalizes and cleans raw crawled data.

Implements cleaning operations from section 3.3.3 of the implementation plan.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataCleaner:
    """Applies cleaning transformations to raw crawled records."""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    def clean_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean all records, returning only valid ones."""
        cleaned = []
        for i, record in enumerate(records):
            try:
                clean_record = self.clean_record(record)
                if clean_record:
                    cleaned.append(clean_record)
            except Exception as e:
                logger.debug(f"Record {i} cleaning failed: {e}")
        logger.info(f"Cleaned {len(cleaned)}/{len(records)} records")
        return cleaned

    def clean_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Apply all cleaning operations to a single record."""
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            cleaned[key] = self.clean_value(value, key)
        return cleaned

    def clean_value(self, value: Any, field_name: str = "") -> Any:
        """Clean a single field value based on its content."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        # 1. Trim whitespace
        value = value.strip()

        # 2. Remove HTML tags
        if "<" in value and ">" in value:
            value = self.strip_html(value)

        # 3. Normalize unicode (NFC)
        value = unicodedata.normalize("NFC", value)

        # 4. Collapse multiple whitespace
        value = re.sub(r"\s+", " ", value).strip()

        # 5. Field-specific transforms
        lower_name = field_name.lower()
        if "price" in lower_name or "cost" in lower_name:
            parsed = self.parse_currency(value)
            if parsed is not None:
                return parsed

        if "date" in lower_name or "time" in lower_name:
            parsed = self.parse_date(value)
            if parsed:
                return parsed

        if "url" in lower_name or "link" in lower_name or "href" in lower_name:
            return self.normalize_url(value)

        return value if value else None

    @staticmethod
    def strip_html(text: str) -> str:
        """Remove HTML tags, keeping text content."""
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    @staticmethod
    def parse_currency(text: str) -> float | None:
        """Parse currency string to float. e.g., '$1,299.00' → 1299.00"""
        numbers = re.findall(r"[\d,.]+", text)
        if numbers:
            try:
                # Handle comma as thousands separator
                cleaned = numbers[0].replace(",", "")
                return float(cleaned)
            except ValueError:
                pass
        return None

    @staticmethod
    def parse_date(text: str) -> str | None:
        """Parse date string to ISO format."""
        try:
            dt = parse_date(text, fuzzy=True)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OverflowError):
            return None

    def normalize_url(self, url: str) -> str:
        """Convert relative URLs to absolute."""
        if not url:
            return url
        if url.startswith(("http://", "https://")):
            return url
        if self.base_url:
            return urljoin(self.base_url, url)
        return url
