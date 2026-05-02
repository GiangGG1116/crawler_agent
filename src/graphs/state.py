"""Graph State — shared state schema for the custom agent LangGraph workflow.

Matches the state spec from section 3.2.1.1 of the implementation plan.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class TemplateFailureState(TypedDict, total=False):
    """Info about why the template path failed."""
    template_id: str
    reason: str
    error_log_excerpt: str


class AnalysisState(TypedDict, total=False):
    """Output of the analyze_site node."""
    analysis_id: str
    url: str
    dom_structure: dict[str, Any]
    pagination: dict[str, Any]
    challenges: list[dict[str, str]]
    recommendation: dict[str, Any]


class GeneratedState(TypedDict, total=False):
    """Output of the generate_crawler_code node."""
    files: list[dict[str, str]]  # [{"filename": ..., "content": ...}]
    entrypoint: Optional[str]


class TestState(TypedDict, total=False):
    """Output of the run_crawler_tests node."""
    passed: bool
    metrics: dict[str, Any]
    errors: list[str]
    sample_records: list[dict[str, Any]]


class AuditState(TypedDict, total=False):
    """Audit trail for the graph execution."""
    phase_used: str
    events: list[dict[str, Any]]


class AgentGraphState(TypedDict, total=False):
    """
    Complete state for the custom_agent_graph LangGraph workflow.

    This state is shared across all nodes and persisted via checkpointing.
    """
    # Input context
    request_id: str
    target_url: str
    domain: str
    web_type: str
    data_type: str
    required_fields: list[str]
    optional_fields: list[str]
    scope_mode: str
    max_pages: int
    max_records: int
    rate_limit_rps: float
    respect_robots_txt: bool
    requires_auth: bool
    proxy_required: bool

    # Template failure context
    template_failure: TemplateFailureState

    # Agent workflow state
    attempt: int
    analysis: Optional[AnalysisState]
    generated: GeneratedState
    test: TestState
    raw_records: list[dict[str, Any]]

    # Decision
    decision: Optional[str]  # "pass" | "retry" | "alert_human"

    # Audit
    audit: AuditState
