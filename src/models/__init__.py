"""Data models for Agent Crawler Data."""

from src.models.request import CrawlRequest, DataSpec, TargetInfo, ScopeConfig, OutputConfig, ScheduleConfig, ConstraintsConfig
from src.models.result import CrawlResult, ValidationResult, QualityReport
from src.models.audit import AuditLog

__all__ = [
    "CrawlRequest",
    "DataSpec",
    "TargetInfo",
    "ScopeConfig",
    "OutputConfig",
    "ScheduleConfig",
    "ConstraintsConfig",
    "CrawlResult",
    "ValidationResult",
    "QualityReport",
    "AuditLog",
]
