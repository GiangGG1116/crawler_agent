"""Node: decide_next — Route graph execution based on test results.

Implements the routing logic:
- test passed → END (handoff to Phase 3)
- test failed + attempt < 3 → retry (back to analyze_site)
- test failed + attempt >= 3 → alert_human
"""

from __future__ import annotations

from typing import Any

from src.graphs.state import AgentGraphState
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def decide_next(state: AgentGraphState) -> dict[str, Any]:
    """Decide the next step based on test results and attempt count."""
    test = state.get("test", {})
    attempt = state.get("attempt", 1)
    request_id = state.get("request_id", "unknown")
    max_retries = get_settings().agent_max_retries

    passed = test.get("passed", False)

    if passed:
        logger.info(f"Tests PASSED on attempt {attempt}", extra={"request_id": request_id, "phase": "phase2"})
        return {"decision": "pass"}
    elif attempt < max_retries:
        next_attempt = attempt + 1
        logger.warning(
            f"Tests FAILED on attempt {attempt}, retrying ({next_attempt}/{max_retries})",
            extra={"request_id": request_id, "phase": "phase2"},
        )
        return {"decision": "retry", "attempt": next_attempt}
    else:
        logger.error(
            f"Tests FAILED after {max_retries} attempts — escalating to human",
            extra={"request_id": request_id, "phase": "phase2"},
        )
        return {"decision": "alert_human"}


def route_decision(state: AgentGraphState) -> str:
    """Routing function for LangGraph conditional edge."""
    decision = state.get("decision", "alert_human")
    if decision == "pass":
        return "end"
    elif decision == "retry":
        return "analyze_site"
    else:
        return "alert_human"


async def alert_human(state: AgentGraphState) -> dict[str, Any]:
    """Terminal node: emit alert for manual review."""
    request_id = state.get("request_id", "unknown")
    url = state.get("target_url", "unknown")
    attempt = state.get("attempt", 0)
    test = state.get("test", {})

    logger.critical(
        f"⚠️  MANUAL REVIEW REQUIRED — request={request_id}, url={url}, "
        f"attempts={attempt}, errors={test.get('errors', [])}",
        extra={"request_id": request_id, "phase": "phase2"},
    )

    # In production, this would send to Slack/email/PagerDuty
    return {
        "decision": "alert_human",
        "audit": {
            "phase_used": "custom_agent",
            "events": [{"type": "alert_human", "message": f"Failed after {attempt} attempts"}],
        },
    }
