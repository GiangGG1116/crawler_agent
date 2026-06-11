"""Service-local schemas for crawler-service.

These are the API contracts owned by crawler-service.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TemplateFailure(BaseModel):
    """Details about why a template failed."""

    template_id: str | None = None
    reason: str = ""
    error_log_excerpt: str = ""


class CrawlerResponse(BaseModel):
    """Typed output contract for crawler-service."""

    status: str = "success"
    records: list[dict[str, Any]] = Field(default_factory=list)
    record_count: int = 0
    template_id: str | None = None
    web_type: str | None = None
    failures: list[TemplateFailure] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
