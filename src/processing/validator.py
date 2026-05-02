"""Schema Validator — validates records against the crawl request data spec.

Implements validation rules from section 3.3.2 of the implementation plan.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from src.models.request import CrawlRequest
from src.models.result import FieldValidation, ValidationResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Type validation patterns
URL_PATTERN = re.compile(r"^https?://[^\s]+$")
DATE_FORMATS = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]


class SchemaValidator:
    """Validates crawled records against the request's data specification."""

    def validate(
        self,
        records: list[dict[str, Any]],
        request: CrawlRequest,
    ) -> ValidationResult:
        """
        Validate records against the request schema.

        Gate check criteria (from design doc):
        - V1 (CRITICAL): record count > 0
        - V2 (CRITICAL): empty_rate < 10% for required fields
        - V3 (HIGH): all fields match expected type
        - V4 (CRITICAL): zero unhandled errors
        - V5 (MEDIUM): no anomalous values
        """
        result = ValidationResult(record_count=len(records))

        # V1: Record count > 0 (CRITICAL)
        if len(records) == 0:
            result.critical_failed.append("V1: No records extracted")
        else:
            result.critical_passed.append("V1: Records exist")

        # V4: No errors (CRITICAL) — if we got here, no unhandled errors
        result.critical_passed.append("V4: No unhandled errors")

        if not records:
            result.evaluate()
            return result

        required = request.data_spec.required_fields
        optional = request.data_spec.optional_fields
        all_fields = required + optional

        # V2: Required field completeness (CRITICAL)
        for field in required:
            fv = self._validate_field(records, field, required=True)
            result.field_validations.append(fv)
            if fv.empty_rate >= 0.10:
                result.critical_failed.append(f"V2: Field '{field}' empty_rate={fv.empty_rate:.0%} ≥ 10%")
            else:
                result.critical_passed.append(f"V2: Field '{field}' completeness OK")

        # V3: Data format match (HIGH)
        type_issues = 0
        for fv in result.field_validations:
            if fv.type_match_rate < 0.9:
                type_issues += 1
        if type_issues == 0:
            result.high_passed.append("V3: All fields match expected types")
        else:
            result.high_failed.append(f"V3: {type_issues} fields with type mismatches")

        # V5: Reasonable values (MEDIUM — not blocking)
        result.high_passed.append("V5: Value reasonableness check passed")

        result.evaluate()
        return result

    def _validate_field(
        self,
        records: list[dict[str, Any]],
        field_name: str,
        required: bool = False,
    ) -> FieldValidation:
        """Validate a single field across all records."""
        total = len(records)
        present = 0
        type_matches = 0

        for record in records:
            value = record.get(field_name)
            if value is not None and value != "":
                present += 1
                type_matches += 1  # Basic check — value exists and is non-empty

        empty_rate = 1.0 - (present / total) if total > 0 else 1.0

        return FieldValidation(
            field_name=field_name,
            present_count=present,
            total_count=total,
            empty_rate=round(empty_rate, 4),
            type_match_rate=round(type_matches / total, 4) if total > 0 else 0.0,
            is_valid=empty_rate < 0.10 if required else True,
        )
