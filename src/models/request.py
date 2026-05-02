"""CrawlRequest — Input schema for crawl jobs.

Matches the Phase 0 Input Schema from the implementation plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


# =============================================================================
# Enums
# =============================================================================

class WebType(str, Enum):
    """Classification of target website type."""
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    API_BASED = "API_BASED"
    PAGINATED = "PAGINATED"
    AUTHENTICATED = "AUTHENTICATED"


class DataType(str, Enum):
    """Type of data to extract."""
    PRODUCTS = "products"
    ARTICLES = "articles"
    COMMENTS = "comments"
    PRICES = "prices"
    USER_INFO = "user_info"
    CUSTOM = "custom"


class CrawlMode(str, Enum):
    """Scope mode for crawling."""
    FULL = "full"
    PAGINATED = "paginated"
    SINGLE_PAGE = "single_page"


class OutputFormat(str, Enum):
    """Output data format."""
    JSON = "json"
    CSV = "csv"
    PARQUET = "parquet"
    DELTA = "delta"


class OutputDestination(str, Enum):
    """Where to store output data."""
    LOCAL_FILE = "local_file"
    S3 = "s3"
    DATA_LAKE = "data_lake"


class ScheduleFrequency(str, Enum):
    """Crawl job frequency."""
    ONE_TIME = "one_time"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    REAL_TIME = "real_time"


# =============================================================================
# Sub-models
# =============================================================================

class TargetInfo(BaseModel):
    """Target website information."""
    url: str = Field(..., description="Target URL to crawl")
    domain: Optional[str] = Field(None, description="Domain name, auto-extracted from URL if not provided")
    web_type: Optional[WebType] = Field(None, description="Detected web type, filled by Phase 0 analyzer")


class DataSpec(BaseModel):
    """Specification of data to extract."""
    data_type: DataType = Field(..., description="Type of data to extract")
    required_fields: list[str] = Field(default_factory=list, description="Fields that must be present in output")
    optional_fields: list[str] = Field(default_factory=list, description="Fields that are nice to have")


class ScopeConfig(BaseModel):
    """Crawl scope configuration."""
    mode: CrawlMode = Field(default=CrawlMode.FULL, description="Crawl mode")
    max_pages: int = Field(default=100, ge=1, le=10000, description="Maximum pages to crawl")
    max_records: int = Field(default=10000, ge=1, le=1000000, description="Maximum records to collect")


class OutputConfig(BaseModel):
    """Output configuration."""
    format: OutputFormat = Field(default=OutputFormat.JSON, description="Output data format")
    destination: OutputDestination = Field(default=OutputDestination.DATA_LAKE, description="Storage destination")


class ScheduleConfig(BaseModel):
    """Schedule configuration for recurring crawls."""
    frequency: ScheduleFrequency = Field(default=ScheduleFrequency.ONE_TIME, description="Crawl frequency")
    start_time: Optional[datetime] = Field(None, description="Scheduled start time")


class AuthConfig(BaseModel):
    """Authentication configuration for protected websites."""
    login_url: Optional[str] = Field(None, description="Login page URL")
    username_selector: Optional[str] = Field(None, description="CSS selector for username field")
    password_selector: Optional[str] = Field(None, description="CSS selector for password field")
    submit_selector: Optional[str] = Field(None, description="CSS selector for submit button")
    username: Optional[str] = Field(None, description="Login username")
    password: Optional[str] = Field(None, description="Login password (use env var reference)")
    success_indicator: Optional[str] = Field(None, description="CSS selector indicating successful login")


class ConstraintsConfig(BaseModel):
    """Crawl constraints and policies."""
    rate_limit_rps: float = Field(default=2.0, ge=0.1, le=100, description="Requests per second limit")
    respect_robots_txt: bool = Field(default=True, description="Whether to respect robots.txt")
    requires_auth: bool = Field(default=False, description="Whether authentication is required")
    auth_config: Optional[AuthConfig] = Field(None, description="Authentication configuration")
    proxy_required: bool = Field(default=False, description="Whether to use proxy rotation")
    timeout_seconds: int = Field(default=30, ge=5, le=300, description="Request timeout in seconds")


# =============================================================================
# Main Request Model
# =============================================================================

class CrawlRequest(BaseModel):
    """Complete crawl job request — Phase 0 input."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique request identifier")
    target: TargetInfo = Field(..., description="Target website information")
    data_spec: DataSpec = Field(..., description="Data extraction specification")
    scope: ScopeConfig = Field(default_factory=ScopeConfig, description="Crawl scope")
    output: OutputConfig = Field(default_factory=OutputConfig, description="Output configuration")
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig, description="Schedule configuration")
    constraints: ConstraintsConfig = Field(default_factory=ConstraintsConfig, description="Crawl constraints")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Request creation timestamp")

    def extract_domain(self) -> str:
        """Extract domain from target URL."""
        from urllib.parse import urlparse
        parsed = urlparse(self.target.url)
        return parsed.netloc or parsed.hostname or ""
