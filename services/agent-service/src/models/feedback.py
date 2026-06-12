"""Human Feedback models."""


import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class HumanFeedbackRequest(BaseModel):
    """Human correction or approval for a domain."""

    domain: str = Field(..., min_length=1, max_length=255)
    feedback: str = Field(..., min_length=1, max_length=10000)
    feedback_type: Literal["correction", "approval", "hint"] = "correction"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        domain = value.strip().lower()
        if "://" in domain or "/" in domain or any(character.isspace() for character in domain):
            raise ValueError("Domain must be a hostname, optionally including a port")
        return domain

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, default=str)) > 20_000:
            raise ValueError("Feedback metadata must be 20 KB or smaller")
        return value
