"""Agent Graph State — defines the shared state for LangGraph workflow."""


from typing import Any

from langgraph.graph import MessagesState


class AgentGraphState(MessagesState):
    """State shared across all graph nodes.

    Extends MessagesState (which provides messages: list[BaseMessage])
    with custom fields for the crawl agent workflow.
    """

    # Input
    request_id: str = ""
    url: str = ""
    data_type: str = "articles"
    required_fields: list[str] = []
    max_pages: int = 10
    max_records: int = 1000
    rate_limit_rps: float = 2.0
    timeout_seconds: int = 30
    respect_robots_txt: bool = True
    initial_analysis: dict[str, Any] | None = None
    template_failure: dict[str, Any] | None = None

    # Memory context (pre-loaded before graph execution)
    domain_context: dict[str, Any] = {}
    known_errors: list[dict[str, Any]] = []
    similar_sites: list[dict[str, Any]] = []
    human_feedback: list[str] = []

    # Phase 0: Analysis
    analysis: dict[str, Any] | None = None

    # Phase 2: Code generation
    crawler_code: str = ""
    crawler_code_path: str = ""
    artifact_path: str = ""

    # Phase 2: Test execution
    test_result: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []

    # Control flow
    attempt: int = 0
    max_retries: int = 3
    status: str = "running"
    errors: list[str] = []
