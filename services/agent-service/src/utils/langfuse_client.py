"""Langfuse client — observability for LLM calls.

Provides lazy initialization and graceful fallback when Langfuse is
unavailable or not configured.
"""


from shared.utils.config import get_settings
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def get_langfuse_handler(
    user_id: str = "agent-service",
    trace_name: str = "agent_trace",
    tags: list[str] | None = None,
):
    """Get a Langfuse callback handler for LangChain/LangGraph.

    Returns None if Langfuse is not configured, so callers should check:
        handler = get_langfuse_handler(...)
        callbacks = [handler] if handler else []
    """
    settings = get_settings()

    if not settings.langfuse_enabled or not settings.langfuse_public_key:
        return None

    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            user_id=user_id,
            trace_name=trace_name,
            tags=tags or [],
        )
        return handler

    except Exception as e:
        logger.warning("Langfuse handler creation failed: %s", e)
        return None


def flush_langfuse() -> None:
    """Flush pending Langfuse events. Call during shutdown."""
    try:
        from langfuse import Langfuse

        client = Langfuse()
        client.flush()
        logger.debug("Langfuse flushed")
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)
