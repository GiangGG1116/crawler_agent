"""CrawlResult — Output schemas for crawl jobs.

Covers validation results, quality reports, and final crawl output.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class CrawlStatus(str, Enum):
    """Overall crawl job status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class QualityGrade(str, Enum):
    """Data quality grade based on score."""

    EXCELLENT = "excellent"  # 90-100%
    GOOD = "good"  # 70-89%
    FAIR = "fair"  # 50-69%
    POOR = "poor"  # < 50%


class PhaseUsed(str, Enum):
    """Which phase produced the final data."""

    TEMPLATE = "template"
    CUSTOM_AGENT = "custom_agent"


# =============================================================================
# Validation Models
# =============================================================================


class FieldValidation(BaseModel):
    """Validation result for a single field."""

    field_name: str
    present_count: int = 0
    total_count: int = 0
    empty_rate: float = 0.0
    type_match_rate: float = 0.0
    is_valid: bool = True
    issues: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Gate check validation result from Phase 1/2."""

    is_valid: bool = False
    record_count: int = 0
    field_validations: list[FieldValidation] = Field(default_factory=list)
    critical_passed: list[str] = Field(default_factory=list)
    critical_failed: list[str] = Field(default_factory=list)
    high_passed: list[str] = Field(default_factory=list)
    high_failed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    decision_reason: str = ""

    def evaluate(self) -> bool:
        """
        Apply the decision rule:
        - ALL CRITICAL passed + ≥ 1 HIGH passed → PASS
        - ANY CRITICAL failed → FAIL
        """
        if self.critical_failed:
            self.is_valid = False
            self.decision_reason = (
                f"CRITICAL checks failed: {', '.join(self.critical_failed)}"
            )
        elif not self.critical_passed:
            self.is_valid = False
            self.decision_reason = "No CRITICAL checks were evaluated"
        elif len(self.high_passed) >= 1:
            self.is_valid = True
            self.decision_reason = "All CRITICAL passed, ≥1 HIGH passed"
        else:
            self.is_valid = False
            self.decision_reason = "All CRITICAL passed but no HIGH checks passed"
        return self.is_valid


# =============================================================================
# Quality Report
# =============================================================================


class QualityReport(BaseModel):
    """Data quality scoring report from Phase 3."""

    completeness_score: float = Field(
        0.0, ge=0, le=100, description="% records with all required fields"
    )
    validity_score: float = Field(
        0.0, ge=0, le=100, description="% fields passing type validation"
    )
    uniqueness_score: float = Field(
        0.0, ge=0, le=100, description="% unique records after dedup"
    )
    freshness_score: float = Field(
        0.0, ge=0, le=100, description="Data freshness score"
    )
    overall_score: float = Field(
        0.0, ge=0, le=100, description="Weighted average quality score"
    )
    grade: QualityGrade = QualityGrade.POOR
    details: dict[str, Any] = Field(default_factory=dict)

    def calculate(self) -> None:
        """Calculate overall score using weighted formula."""
        self.overall_score = (
            self.completeness_score * 0.40
            + self.validity_score * 0.30
            + self.uniqueness_score * 0.20
            + self.freshness_score * 0.10
        )
        if self.overall_score >= 90:
            self.grade = QualityGrade.EXCELLENT
        elif self.overall_score >= 70:
            self.grade = QualityGrade.GOOD
        elif self.overall_score >= 50:
            self.grade = QualityGrade.FAIR
        else:
            self.grade = QualityGrade.POOR


# =============================================================================
# Crawl Result
# =============================================================================


class TemplateFailure(BaseModel):
    """Details about why a template failed."""

    template_id: str | None = None
    reason: str = ""
    error_log_excerpt: str = ""


class CrawlResult(BaseModel):
    """Final output of a crawl job."""

    request_id: str
    status: CrawlStatus = CrawlStatus.PENDING
    phase_used: PhaseUsed | None = None
    template_id: str | None = None
    template_failure: TemplateFailure | None = None
    detected_web_type: str | None = None
    compliance_decision: str = "allowed"

    # Data
    raw_records: list[dict[str, Any]] = Field(default_factory=list)
    clean_records: list[dict[str, Any]] = Field(default_factory=list)
    rejected_records: list[dict[str, Any]] = Field(default_factory=list)

    # Reports
    validation: ValidationResult | None = None
    quality: QualityReport | None = None

    # Metadata
    attempts: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_path: str | None = None
