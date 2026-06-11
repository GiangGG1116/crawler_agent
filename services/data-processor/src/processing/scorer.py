"""QualityScorer — scores data quality using the weighted formula.

Scoring formula (from shared QualityReport):
  overall = completeness*0.40 + validity*0.30 + uniqueness*0.20 + freshness*0.10
"""

from __future__ import annotations

from typing import Any

from shared.models.result import QualityReport
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class QualityScorer:
    """Score data quality and produce a QualityReport."""

    def score(
        self,
        raw_count: int,
        clean_count: int,
        rejected_count: int,
        required_fields: list[str],
        records: list[dict[str, Any]],
    ) -> QualityReport:
        """Calculate quality metrics and return a QualityReport."""
        report = QualityReport()

        if not records:
            report.calculate()
            return report

        # Completeness: % of records with all required fields non-empty
        if required_fields:
            complete = sum(1 for r in records if all(r.get(f) for f in required_fields))
            report.completeness_score = (complete / len(records)) * 100
        else:
            report.completeness_score = 100.0

        # Validity: % of values that are of expected type (non-null, non-empty)
        total_values = 0
        valid_values = 0
        for record in records:
            for key, val in record.items():
                total_values += 1
                if val is not None and val != "":
                    valid_values += 1
        report.validity_score = (
            (valid_values / total_values * 100) if total_values else 0
        )

        # Uniqueness: ratio of unique to total
        report.uniqueness_score = (clean_count / raw_count * 100) if raw_count else 0

        # Freshness: defaults to 100 (we assume data is fresh since we just crawled it)
        report.freshness_score = 100.0

        # Calculate overall
        report.calculate()

        logger.info(
            "Quality: completeness=%.1f validity=%.1f uniqueness=%.1f → overall=%.1f (%s)",
            report.completeness_score,
            report.validity_score,
            report.uniqueness_score,
            report.overall_score,
            report.grade.value,
        )

        return report
