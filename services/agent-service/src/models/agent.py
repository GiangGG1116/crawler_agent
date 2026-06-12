"""Input/Output models for Agent execution."""


import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from shared.utils.network import validate_http_url_syntax


class AgentRunRequest(BaseModel):
    """Input contract for POST /agent/run."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    url: str = Field(..., min_length=8, max_length=2048, description="Public HTTP(S) target URL")
    data_type: str = Field(default="articles", min_length=1, max_length=64)
    required_fields: list[str] = Field(default_factory=list, max_length=100)
    max_pages: int = Field(default=10, ge=1, le=1000)
    max_records: int = Field(default=1000, ge=1, le=100000)
    rate_limit_rps: float = Field(default=2.0, ge=0.1, le=20)
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    respect_robots_txt: bool = True
    initial_analysis: dict[str, Any] | None = None
    template_failure: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return validate_http_url_syntax(value)

    @field_validator("required_fields")
    @classmethod
    def validate_required_fields(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(field.strip() for field in values if field.strip()))
        if any(len(field) > 128 for field in cleaned):
            raise ValueError("Required field names must be 128 characters or fewer")
        return cleaned

    @field_validator("initial_analysis", "template_failure")
    @classmethod
    def validate_context_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value, default=str)) > 100_000:
            raise ValueError("Agent context payload must be 100 KB or smaller")
        return value


class AgentResponse(BaseModel):
    """Output contract for agent-service."""

    status: Literal["success", "failed", "max_retries_exceeded"] = "success"
    records: list[dict[str, Any]] = Field(default_factory=list)
    record_count: int = 0
    crawler_code: str | None = None
    artifact_path: str | None = None
    attempts: int = 0
    analysis: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
