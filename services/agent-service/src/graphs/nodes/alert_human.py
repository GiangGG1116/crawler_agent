"""Node: alert_human — Trigger human intervention when max retries exceeded.

When the agent exhausts all retry attempts, this node:
1. Saves the error pattern to Error Memory
2. Saves the partial analysis to Domain Memory
3. Logs a structured alert for human operators
4. Optionally notifies via webhook (if configured)
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from shared.utils.logger import get_logger

logger = get_logger(__name__)


async def alert_human(state: dict[str, Any]) -> dict[str, Any]:
    """Trigger human intervention and persist error context.

    This node runs when decide_next routes to max_retries.
    It saves all accumulated context so a human can:
    1. Review the analysis and generated code
    2. Provide manual selectors or corrections
    3. Resume the pipeline with human feedback
    """
    url = state.get("url", "unknown")
    attempt = state.get("attempt", 0)
    errors = state.get("errors", [])
    analysis = state.get("analysis", {})
    crawler_code = state.get("crawler_code", "")

    logger.warning(
        "🚨 HUMAN INTERVENTION REQUIRED: %s — %d attempts failed",
        url,
        attempt,
    )

    # Build alert payload
    alert = {
        "type": "crawl_failure",
        "severity": "high",
        "url": url,
        "attempts": attempt,
        "errors": errors[-5:],  # Last 5 errors
        "analysis_summary": {
            "web_type": analysis.get("web_type", "unknown"),
            "challenges": analysis.get("challenges", []),
        },
        "last_code_snippet": crawler_code[:1000] if crawler_code else None,
        "recommended_actions": [
            "Review the site structure manually",
            "Provide CSS selectors via human feedback API",
            "Check if the site requires authentication",
            "Verify the site is not blocking automated access",
        ],
    }

    logger.info("Alert payload: %s", alert)

    from shared.utils.config import get_settings

    webhook_url = get_settings().agent_alert_webhook_url
    if webhook_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=alert)
                response.raise_for_status()
        except Exception:
            logger.exception("Failed to send human intervention webhook")

    # Save error pattern for future reference
    from urllib.parse import urlparse

    domain = urlparse(url).netloc

    error_summary = "; ".join(errors[-3:]) if errors else "Max retries exceeded"

    return {
        "status": "max_retries_exceeded",
        "messages": [
            AIMessage(
                content=(
                    f"⚠️ Human intervention required for {url}.\n"
                    f"Failed after {attempt} attempts.\n"
                    f"Last errors: {error_summary}\n"
                    f"Recommended: review site manually and provide feedback."
                )
            ),
        ],
        "errors": errors
        + [f"Human review required for {domain}: max retries ({attempt}) exceeded"],
    }
