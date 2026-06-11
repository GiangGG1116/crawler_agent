"""Schemas for data-processor service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    """Input contract for POST /process."""

    request_id: str
    source_url: str
    raw_records: list[dict[str, Any]]
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    output_format: str = "json"
    output_destination: str = "data_lake"


class ProcessorResponse(BaseModel):
    """Output contract for data-processor."""

    status: str = "success"
    clean_records: list[dict[str, Any]] = Field(default_factory=list)
    rejected_records: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] | None = None
    output_path: str | None = None
    errors: list[str] = Field(default_factory=list)
