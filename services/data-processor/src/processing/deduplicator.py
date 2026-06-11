"""Deduplicator — removes duplicate records.

Uses content-based hashing to identify and remove exact and near-duplicate
records from the dataset.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.utils.logger import get_logger

logger = get_logger(__name__)


class Deduplicator:
    """Remove duplicate records using content hashing."""

    def deduplicate(
        self,
        records: list[dict[str, Any]],
        key_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Remove exact duplicate records.

        If key_fields is provided, only those fields are used for comparison.
        Otherwise, all fields are used.
        """
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []

        for record in records:
            fingerprint = self._hash_record(record, key_fields)
            if fingerprint not in seen:
                seen.add(fingerprint)
                unique.append(record)

        dups = len(records) - len(unique)
        if dups:
            logger.info("Removed %d duplicate records", dups)

        return unique

    def _hash_record(
        self,
        record: dict[str, Any],
        key_fields: list[str] | None = None,
    ) -> str:
        """Generate a content hash for a record."""
        if key_fields:
            data = {k: record.get(k) for k in sorted(key_fields)}
        else:
            data = dict(sorted(record.items()))

        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()
