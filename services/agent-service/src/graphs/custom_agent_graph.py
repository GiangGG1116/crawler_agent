"""Custom Agent Graph — LangGraph workflow for custom crawler generation.

Implements the multi-agent loop with 6-layer memory integration:

  analyze_site → generate_code → run_tests → decide_next
                                                ↓ success → END
                                                ↓ retry   → analyze_site
                                                ↓ max_retries → alert_human → END

Memory layers used:
  1. Checkpointer — durable Redis or SQLite state (survives restarts)
  2. Domain Memory — past crawl strategies for this domain
  3. Error Patterns — known failures to avoid
  4. Conversation Buffer — recent messages for LLM context
  5. Vector KB — similar sites from ChromaDB for RAG
  6. Human Feedback — expert corrections and hints
"""


from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from shared.utils.config import Settings
from shared.utils.logger import get_logger
from src.graphs.state import AgentGraphState
from src.memory import MemoryManager

logger = get_logger(__name__)


class CustomAgentGraph:
    """LangGraph-based agent for generating custom crawlers.

    Integrates all 6 memory layers and a durable checkpointer.
    """

    def __init__(self, settings: Settings, memory_manager: MemoryManager, checkpointer: Any):
        self._settings = settings
        self._memory = memory_manager
        self._graph = self._build_graph(checkpointer)

    def _build_graph(self, checkpointer: Any) -> StateGraph:
        """Build the LangGraph workflow with all nodes and edges."""
        from src.graphs.nodes.alert_human import alert_human
        from src.graphs.nodes.analyze_site import analyze_site
        from src.graphs.nodes.decide_next import decide_next
        from src.graphs.nodes.generate_code import generate_crawler_code
        from src.graphs.nodes.run_tests import run_crawler_tests

        graph = StateGraph(AgentGraphState)

        # Add nodes
        graph.add_node("prepare", lambda state: {})
        graph.add_node("analyze_site", analyze_site)
        graph.add_node("generate_code", generate_crawler_code)
        graph.add_node("run_tests", run_crawler_tests)
        graph.add_node("decide_next", decide_next)
        graph.add_node("alert_human", alert_human)

        # Set entry point
        graph.set_entry_point("prepare")
        graph.add_conditional_edges(
            "prepare",
            lambda state: "cached" if state.get("crawler_code") else "generate",
            {"cached": "run_tests", "generate": "analyze_site"},
        )

        # Linear edges
        graph.add_edge("analyze_site", "generate_code")
        graph.add_edge("generate_code", "run_tests")
        graph.add_edge("run_tests", "decide_next")

        # Conditional routing from decide_next
        graph.add_conditional_edges(
            "decide_next",
            self._route_decision,
            {
                "success": END,
                "retry": "analyze_site",
                "max_retries": "alert_human",
            },
        )

        # alert_human always ends the graph
        graph.add_edge("alert_human", END)

        # Compile with checkpointer for durable state
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _route_decision(state: AgentGraphState) -> str:
        """Route based on decision status in state."""
        status = state.get("status", "running")
        if status == "success":
            return "success"
        elif status == "max_retries_exceeded":
            return "max_retries"
        else:
            return "retry"

    async def run(
        self,
        request_id: str,
        url: str,
        data_type: str = "articles",
        required_fields: list[str] | None = None,
        max_pages: int = 10,
        max_records: int = 1000,
        rate_limit_rps: float = 2.0,
        timeout_seconds: int = 30,
        respect_robots_txt: bool = True,
        initial_analysis: dict[str, Any] | None = None,
        template_failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the custom agent graph with full 6-layer memory integration.

        Memory flow:
        1. Pre-load all memory layers into initial state
        2. Graph nodes read from state, append to conversation buffer
        3. Checkpointer persists state at every node transition
        4. On completion, results are saved back to memory layers
        """
        domain = urlparse(url).netloc
        logger.info("Starting agent run for: %s (domain: %s)", url, domain)

        # ── Pre-load all memory layers ────────────────────────────────────

        # Layer 2: Domain Memory
        domain_context = await self._memory.get_domain_context(domain)

        # Layer 3: Error Patterns
        known_errors = await self._memory.get_known_errors(domain)

        # Layer 5: Vector KB (Similar Sites)
        similar_sites = await self._memory.get_similar_sites(domain, data_type)

        # Layer 6: Human Feedback
        human_feedback = await self._memory.get_human_feedback(domain)

        # Layer 4: Conversation Buffer (inject previous session context)
        session_id = f"{domain}:{data_type}"
        conversation_history = await self._memory.get_conversation_history(session_id)

        logger.info(
            "Memory pre-loaded: domain_ctx=%s, errors=%d, similar=%d, feedback=%d, conv=%d",
            bool(domain_context),
            len(known_errors),
            len(similar_sites),
            len(human_feedback),
            len(conversation_history),
        )

        # ── Build initial state ───────────────────────────────────────────

        initial_state = {
            "request_id": request_id,
            "url": url,
            "data_type": data_type,
            "required_fields": required_fields or [],
            "max_pages": max_pages,
            "max_records": max_records,
            "rate_limit_rps": rate_limit_rps,
            "timeout_seconds": timeout_seconds,
            "respect_robots_txt": respect_robots_txt,
            "initial_analysis": initial_analysis,
            "template_failure": template_failure,
            # Memory context
            "domain_context": domain_context,
            "known_errors": known_errors,
            "similar_sites": similar_sites,
            "human_feedback": [fb.get("feedback", "") for fb in human_feedback],
            # Control flow
            "attempt": 0,
            "max_retries": self._settings.agent_max_retries,
            "status": "running",
            "errors": [],
            "messages": [
                (
                    HumanMessage(content=entry["content"])
                    if entry.get("role") == "human"
                    else AIMessage(content=entry["content"])
                )
                for entry in conversation_history
            ],
        }
        artifact_path = domain_context.get("artifact_path")
        if artifact_path:
            approved_root = (self._settings.generated_crawlers_dir / "approved").resolve()
            cached_path = Path(artifact_path).resolve()
            if cached_path.is_file() and cached_path.is_relative_to(approved_root):
                initial_state["crawler_code"] = cached_path.read_text(encoding="utf-8")
                initial_state["artifact_path"] = str(cached_path)
                initial_state["analysis"] = domain_context.get("analysis")
                logger.info("Testing approved cached crawler for %s", domain)

        # ── Execute graph with checkpointer ───────────────────────────────

        try:
            config = {
                "configurable": {
                    "thread_id": f"crawl:{request_id}",
                }
            }

            final_state = await self._graph.ainvoke(initial_state, config=config)

            # ── Post-run: persist results back to memory layers ───────────

            status = final_state.get("status", "failed")

            if status == "success":
                # Save to Domain Memory + Vector KB
                await self._memory.save_success(
                    domain=domain,
                    crawler_code=final_state.get("crawler_code", ""),
                    analysis=final_state.get("analysis"),
                    artifact_path=final_state.get("artifact_path"),
                )
                logger.info("Success context persisted for %s", domain)

            elif status == "max_retries_exceeded":
                # Save error patterns
                for error in final_state.get("errors", [])[-3:]:
                    await self._memory.save_error(
                        domain=domain,
                        error=error,
                        error_type="max_retries",
                        context={"analysis": final_state.get("analysis")},
                    )
                logger.info("Error patterns persisted for %s", domain)

            # Update conversation buffer
            new_messages = final_state.get("messages", [])[len(conversation_history) :]
            for msg in new_messages:
                role = "human" if hasattr(msg, "type") and msg.type == "human" else "ai"
                content = msg.content if hasattr(msg, "content") else str(msg)
                await self._memory.add_message(session_id, role, content)

            return {
                "status": status,
                "records": final_state.get("records", []),
                "crawler_code": final_state.get("crawler_code"),
                "artifact_path": final_state.get("artifact_path"),
                "test_result": final_state.get("test_result"),
                "attempts": final_state.get("attempt", 0),
                "analysis": final_state.get("analysis"),
                "errors": final_state.get("errors", []),
            }

        except Exception as e:
            logger.exception("Agent graph execution failed: %s", e)

            # Save error for future reference
            await self._memory.save_error(
                domain=domain,
                error=str(e),
                error_type="graph_exception",
            )

            return {
                "status": "failed",
                "records": [],
                "errors": [str(e)],
            }

    async def get_state(self, request_id: str) -> dict[str, Any]:
        """Return the latest durable state for an agent run."""
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": f"crawl:{request_id}"}})
        return dict(snapshot.values) if snapshot and snapshot.values else {}
