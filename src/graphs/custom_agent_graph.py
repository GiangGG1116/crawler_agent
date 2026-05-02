"""Custom Agent Graph — LangGraph workflow definition.

Implements the Phase 2 pipeline:
  analyze_site → generate_crawler_code → run_crawler_tests → decide_next
  with conditional routing for retry (max 3) or alert_human.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from src.graphs.state import AgentGraphState
from src.graphs.nodes.analyze_site import analyze_site
from src.graphs.nodes.generate_code import generate_crawler_code
from src.graphs.nodes.run_tests import run_crawler_tests
from src.graphs.nodes.decide_next import alert_human, decide_next, route_decision
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_custom_agent_graph() -> StateGraph:
    """
    Build and compile the custom agent LangGraph workflow.

    Graph structure:
        START → analyze_site → generate_crawler_code → run_crawler_tests → decide_next
                ↑                                                              │
                └──────────── retry (attempt < 3) ─────────────────────────────┘
                                                                               │
                                                                    pass → END
                                                                    alert → alert_human → END
    """
    graph = StateGraph(AgentGraphState)

    # Add nodes
    graph.add_node("analyze_site", analyze_site)
    graph.add_node("generate_crawler_code", generate_crawler_code)
    graph.add_node("run_crawler_tests", run_crawler_tests)
    graph.add_node("decide_next", decide_next)
    graph.add_node("alert_human", alert_human)

    # Set entry point
    graph.set_entry_point("analyze_site")

    # Sequential edges
    graph.add_edge("analyze_site", "generate_crawler_code")
    graph.add_edge("generate_crawler_code", "run_crawler_tests")
    graph.add_edge("run_crawler_tests", "decide_next")

    # Conditional routing from decide_next
    graph.add_conditional_edges(
        "decide_next",
        route_decision,
        {
            "end": END,
            "analyze_site": "analyze_site",
            "alert_human": "alert_human",
        },
    )

    # Terminal node
    graph.add_edge("alert_human", END)

    return graph


class CustomAgentGraphRunner:
    """Runner for the custom agent graph with checkpointing support."""

    def __init__(self):
        self._graph = build_custom_agent_graph()
        self._compiled = None

    def compile(self, checkpointer=None):
        """Compile the graph with optional checkpointing."""
        kwargs = {}
        if checkpointer:
            kwargs["checkpointer"] = checkpointer
        self._compiled = self._graph.compile(**kwargs)
        return self._compiled

    async def run(
        self,
        request_id: str,
        target_url: str,
        web_type: str,
        required_fields: list[str],
        template_failure: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the custom agent graph.

        Returns:
            Final state dict with raw_records and test results.
        """
        if not self._compiled:
            self.compile()

        initial_state: AgentGraphState = {
            "request_id": request_id,
            "target_url": target_url,
            "web_type": web_type,
            "required_fields": required_fields,
            "template_failure": template_failure or {},
            "attempt": 1,
            "analysis": None,
            "generated": {"files": [], "entrypoint": None},
            "test": {"passed": False, "metrics": {}, "errors": [], "sample_records": []},
            "raw_records": [],
            "decision": None,
            "audit": {"phase_used": "custom_agent", "events": []},
            **kwargs,
        }

        logger.info(f"Starting custom agent graph for {target_url}", extra={"request_id": request_id})

        config = {"configurable": {"thread_id": request_id}}
        result = await self._compiled.ainvoke(initial_state, config=config)

        return result
