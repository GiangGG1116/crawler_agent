"""Schema Validator — validates processed records against field specs.

Returns two lists: (valid_records, invalid_records).
"""

from __future__ import annotations

from typing import Any

from shared.utils.logger import get_logger

logger = get_logger(__name__)


class SchemaValidator:
    """Validate records against required/optional field specifications."""

    def validate(
        self,
        records: list[dict[str, Any]],
        required_fields: list[str],
        optional_fields: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split records into valid and invalid based on field requirements.

        Returns:
            Tuple of (valid_records, invalid_records).
        """
        if not required_fields:
            return records, []

        valid = []
        invalid = []

        for record in records:
            missing = [f for f in required_fields if not record.get(f)]
            if missing:
                record["_rejection_reason"] = f"Missing fields: {missing}"
                invalid.append(record)
            else:
                valid.append(record)

        logger.info(
            "Validation: %d valid, %d invalid (required: %s)",
            len(valid),
            len(invalid),
            required_fields,
        )
        return valid, invalid
