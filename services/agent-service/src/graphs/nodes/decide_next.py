"""Node: decide_next — Decision routing for the agent loop.

Evaluates test results and decides whether to:
  - SUCCESS: Move to END (records collected successfully)
  - RETRY: Go back to analyze_site with increased attempt count
  - MAX_RETRIES: Stop and alert human
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from shared.utils.logger import get_logger

logger = get_logger(__name__)


async def decide_next(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate test results and decide next action."""
    test_result = state.get("test_result", {})
    records = state.get("records", [])
    attempt = state.get("attempt", 0)
    max_retries = state.get("max_retries", 3)

    test_status = test_result.get("status", "error")

    # Success: we got records
    if test_status == "success" and len(records) > 0:
        logger.info(
            "Decision: SUCCESS — %d records after %d attempt(s)",
            len(records),
            attempt + 1,
        )
        return {
            "status": "success",
            "attempt": attempt + 1,
            "messages": [
                AIMessage(
                    content=f"Success! Collected {len(records)} records in {attempt + 1} attempt(s)."
                ),
            ],
        }

    # Max retries exceeded
    if attempt + 1 >= max_retries:
        logger.warning(
            "Decision: MAX_RETRIES_EXCEEDED — %d attempts exhausted for %s",
            max_retries,
            state.get("url"),
        )
        return {
            "status": "max_retries_exceeded",
            "attempt": attempt + 1,
            "errors": state.get("errors", [])
            + [f"Max retries ({max_retries}) exceeded without successful crawl"],
            "messages": [
                AIMessage(
                    content=f"Failed after {max_retries} attempts. Human intervention needed."
                ),
            ],
        }

    # Retry: go back to analyze with accumulated context
    error_msg = test_result.get("error", "Unknown error")
    logger.info(
        "Decision: RETRY — attempt %d/%d, error: %s",
        attempt + 1,
        max_retries,
        error_msg,
    )

    return {
        "status": "retry",
        "attempt": attempt + 1,
        "messages": [
            AIMessage(
                content=f"Attempt {attempt + 1} failed: {error_msg}. Retrying..."
            ),
        ],
    }
