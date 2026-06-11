"""Schema Validator — validates crawled records against field specifications."""

from __future__ import annotations

from typing import Any

from shared.utils.logger import get_logger

logger = get_logger(__name__)


class SchemaValidator:
    """Validates crawled records against expected field specifications."""

    def validate_records(
        self,
        records: list[dict[str, Any]],
        required_fields: list[str],
    ) -> list[dict[str, Any]]:
        """Filter records that have all required fields with non-empty values.

        Returns only valid records.
        """
        if not required_fields:
            return records

        valid = []
        for i, record in enumerate(records):
            missing = [f for f in required_fields if not record.get(f)]
            if missing:
                logger.debug("Record %d missing fields: %s", i, missing)
            else:
                valid.append(record)

        logger.info(
            "Validation: %d/%d records passed (required: %s)",
            len(valid),
            len(records),
            required_fields,
        )
        return valid
