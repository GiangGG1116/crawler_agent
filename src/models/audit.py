"""AuditLog — Tracking schema for every crawl job.

Provides 100% audit trail coverage as required by non-functional requirements.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.models.result import CrawlStatus, PhaseUsed


class AuditEvent(BaseModel):
    """Single event within the audit trail."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    phase: str = ""
    event_type: str = ""
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditLog(BaseModel):
    """Complete audit log for a crawl job."""

    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_url: str = ""
    phase_used: Optional[PhaseUsed] = None
    template_id: Optional[str] = None
    attempts: int = 0
    records_raw: int = 0
    records_clean: int = 0
    records_rejected: int = 0
    quality_score: float = 0.0
    duration_seconds: float = 0.0
    status: CrawlStatus = CrawlStatus.PENDING
    errors: list[str] = Field(default_factory=list)
    events: list[AuditEvent] = Field(default_factory=list)

    def add_event(self, phase: str, event_type: str, message: str, **metadata: Any) -> None:
        """Add a timestamped event to the audit trail."""
        self.events.append(
            AuditEvent(
                phase=phase,
                event_type=event_type,
                message=message,
                metadata=metadata,
            )
        )

    def finalize(
        self,
        status: CrawlStatus,
        phase_used: PhaseUsed,
        records_raw: int,
        records_clean: int,
        records_rejected: int,
        quality_score: float,
        duration_seconds: float,
    ) -> None:
        """Finalize audit log with final results."""
        self.status = status
        self.phase_used = phase_used
        self.records_raw = records_raw
        self.records_clean = records_clean
        self.records_rejected = records_rejected
        self.quality_score = quality_score
        self.duration_seconds = duration_seconds
        self.add_event(
            phase="finalize",
            event_type="completed",
            message=f"Job completed with status={status.value}, quality={quality_score:.1f}%",
        )
