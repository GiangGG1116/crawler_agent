"""Quality Scorer — calculates data quality score for crawled data.

Implements the weighted scoring formula from section 3.3.4 of the design doc:
  Quality Score = Completeness(40%) + Validity(30%) + Uniqueness(20%) + Freshness(10%)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.models.result import QualityReport
from src.utils.logger import get_logger

logger = get_logger(__name__)


class QualityScorer:
    """Calculate data quality score for a set of records."""

    def score(
        self,
        clean_records: list[dict[str, Any]],
        total_before_dedup: int,
        required_fields: list[str],
        crawl_timestamp: datetime | None = None,
    ) -> QualityReport:
        """
        Calculate quality scores and return a QualityReport.

        Args:
            clean_records: Records after cleaning and dedup.
            total_before_dedup: Record count before deduplication.
            required_fields: Fields that must be present.
            crawl_timestamp: When the crawl started (for freshness).
        """
        report = QualityReport()

        if not clean_records:
            report.calculate()
            return report

        # Completeness (40%): % records with ALL required fields present
        if required_fields:
            complete = sum(
                1 for r in clean_records
                if all(r.get(f) is not None and r.get(f) != "" for f in required_fields)
            )
            report.completeness_score = (complete / len(clean_records)) * 100
        else:
            report.completeness_score = 100.0

        # Validity (30%): % fields passing basic type validation
        total_fields = 0
        valid_fields = 0
        for r in clean_records:
            for key, value in r.items():
                total_fields += 1
                if value is not None:
                    valid_fields += 1
        report.validity_score = (valid_fields / total_fields * 100) if total_fields > 0 else 100.0

        # Uniqueness (20%): % unique records (after dedup / before dedup)
        if total_before_dedup > 0:
            report.uniqueness_score = (len(clean_records) / total_before_dedup) * 100
        else:
            report.uniqueness_score = 100.0

        # Freshness (10%): Based on time since crawl
        if crawl_timestamp:
            age_hours = (datetime.now(timezone.utc) - crawl_timestamp.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age_hours < 1:
                report.freshness_score = 100.0
            elif age_hours < 24:
                report.freshness_score = 90.0
            elif age_hours < 168:  # 1 week
                report.freshness_score = 70.0
            else:
                report.freshness_score = 50.0
        else:
            report.freshness_score = 100.0  # Just crawled

        report.calculate()

        report.details = {
            "total_records": len(clean_records),
            "complete_records": int(report.completeness_score * len(clean_records) / 100),
            "before_dedup": total_before_dedup,
            "required_fields": required_fields,
        }

        logger.info(
            f"Quality Score: {report.overall_score:.1f}% ({report.grade.value}) — "
            f"C={report.completeness_score:.0f}% V={report.validity_score:.0f}% "
            f"U={report.uniqueness_score:.0f}% F={report.freshness_score:.0f}%"
        )
        return report
