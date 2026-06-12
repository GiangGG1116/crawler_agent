"""Agent Service FastAPI application."""


import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Response, status

from shared.utils.config import get_settings
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logger import get_logger
from src.artifacts import cleanup_generated_artifacts
from src.graphs.custom_agent_graph import CustomAgentGraph
from src.memory import MemoryManager
from src.memory.checkpointer import CheckpointManager
from src.routers import agent
from src.utils.langfuse_client import flush_langfuse

logger = get_logger(__name__)
_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize durable dependencies and the compiled graph once per worker."""
    settings = get_settings()
    settings.validate_production(require_internal_auth=True, require_sandbox=True)
    logger.info("Starting Agent Service")

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception:
        if settings.app_env.lower() == "production":
            raise
        logger.warning("Redis unavailable; using development memory fallback", exc_info=True)
        await redis_client.aclose()
        redis_client = None

    checkpoint_manager = CheckpointManager(settings)
    checkpointer = await checkpoint_manager.start()
    memory_manager = MemoryManager(settings, redis_client)
    app.state.settings = settings
    app.state.redis = redis_client
    app.state.memory_manager = memory_manager
    app.state.checkpoint_manager = checkpoint_manager
    app.state.agent_graph = CustomAgentGraph(settings, memory_manager, checkpointer)
    removed = cleanup_generated_artifacts(settings)
    logger.info("Agent Service initialized; removed %d stale artifacts", removed)

    yield

    await checkpoint_manager.close()
    if redis_client is not None:
        await redis_client.aclose()
    flush_langfuse()
    logger.info("Agent Service shutdown complete")


app = FastAPI(
    title="Agent Crawler - Agent Service",
    version="1.1.0",
    description="Phase 2: AI-powered custom crawler generation via LangGraph",
    lifespan=lifespan,
)
register_exception_handlers(app)
app.include_router(agent.router, prefix="/agent", tags=["agent"])


@app.get("/healthz", tags=["system"])
async def healthcheck():
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "agent-service",
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
        "llm_provider": settings.default_llm_provider.value,
    }


@app.get("/readyz", tags=["system"])
async def readiness(response: Response):
    settings = get_settings()
    memory = await app.state.memory_manager.healthcheck()
    checkpoint = app.state.checkpoint_manager
    llm_configured = bool(
        settings.openai_api_key if settings.default_llm_provider.value == "openai" else settings.anthropic_api_key
    )
    ready = memory["redis"] and checkpoint.durable and llm_configured
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "degraded",
        "memory": memory,
        "checkpoint_backend": checkpoint.backend,
        "checkpoint_durable": checkpoint.durable,
        "llm_configured": llm_configured,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="127.0.0.1", port=8007, log_level="debug")