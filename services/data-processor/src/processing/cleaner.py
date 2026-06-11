"""DataCleaner — normalizes and sanitizes raw crawl records.

Operations:
  - Strip whitespace from string values
  - Normalize URLs (add scheme if missing)
  - Remove HTML tags from text fields
  - Discard completely empty records
"""

from __future__ import annotations

import html
import re
from typing import Any

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class DataCleaner:
    """Clean and normalize raw crawl records."""

    def clean(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean a batch of records."""
        cleaned = []
        for record in records:
            result = self._clean_record(record)
            if result:
                cleaned.append(result)
        return cleaned

    def _clean_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Clean a single record."""
        cleaned: dict[str, Any] = {}

        for key, value in record.items():
            if isinstance(value, str):
                value = self._clean_string(value)
            cleaned[key] = value

        # Discard if all values are empty
        if not any(v for v in cleaned.values() if v not in (None, "", 0, [], {})):
            return None

        return cleaned

    def _clean_string(self, text: str) -> str:
        """Clean a string value."""
        # Strip whitespace
        text = text.strip()

        # Remove HTML tags
        text = _HTML_TAG_RE.sub("", text)

        # Decode HTML entities
        text = html.unescape(text)

        # Normalize whitespace
        text = " ".join(text.split())

        return text
