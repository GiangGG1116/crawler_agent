"""Deduplicator — removes duplicate records from crawled data."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class Deduplicator:
    """Remove duplicate records using content hashing."""

    def __init__(self, key_fields: list[str] | None = None):
        """
        Args:
            key_fields: Fields to use for dedup key. If None, uses entire record.
        """
        self.key_fields = key_fields

    def deduplicate(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """
        Remove duplicates from records.

        Returns:
            Tuple of (unique_records, duplicates_removed_count).
        """
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        dupes = 0

        for record in records:
            key = self._compute_hash(record)
            if key not in seen:
                seen.add(key)
                unique.append(record)
            else:
                dupes += 1

        if dupes:
            logger.info(f"Deduplication: {len(records)} → {len(unique)} records ({dupes} duplicates removed)")
        return unique, dupes

    def _compute_hash(self, record: dict[str, Any]) -> str:
        """Compute a deterministic hash for a record."""
        if self.key_fields:
            key_data = {k: record.get(k) for k in self.key_fields}
        else:
            key_data = record

        serialized = json.dumps(key_data, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()
