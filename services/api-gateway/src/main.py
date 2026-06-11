"""API Gateway — FastAPI application entry point.

Routes incoming crawl requests to the appropriate microservices.
Jobs run in the background — POST returns immediately with a job_id.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.utils.config import get_settings
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Track active background tasks so we can wait for them on shutdown
_background_tasks: set[asyncio.Task] = set()
_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    import redis.asyncio as aioredis

    settings = get_settings()

    # --- Startup ---
    logger.info("Starting API Gateway")
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis_client

    from src.services.job_store import JobStore

    app.state.job_store = JobStore(redis_client)
    app.state.http_client = httpx.AsyncClient(timeout=300)

    yield

    # --- Shutdown: gracefully wait for running tasks ---
    logger.info(
        "Shutting down — waiting for %d background tasks", len(_background_tasks)
    )
    if _background_tasks:
        done, pending = await asyncio.wait(_background_tasks, timeout=30)
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await app.state.http_client.aclose()
    await app.state.redis.aclose()
    logger.info("API Gateway shutdown complete")


app = FastAPI(
    title="Agent Crawler — API Gateway",
    version="1.0.0",
    description="Intelligent Web Data Crawling Platform",
    lifespan=lifespan,
)

# --- CORS ---
settings = get_settings()
origins = (
    [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    if settings.allowed_origins
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# --- Global exception handlers ---
register_exception_handlers(app)

# --- Request tracing (X-Request-ID propagation) ---
from src.middleware.tracing import RequestTracingMiddleware

app.add_middleware(RequestTracingMiddleware)

# --- Routers ---
from src.routers import crawl

app.include_router(crawl.router, prefix="/api/v1", tags=["crawl"])


# --- Health check ---
@app.get("/healthz", tags=["system"])
async def healthcheck():
    """Health check endpoint with Redis connectivity and task count."""
    redis_ok = False
    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception:
        pass

    uptime = round(time.monotonic() - _start_time, 1)
    return {
        "status": "healthy" if redis_ok else "degraded",
        "service": "api-gateway",
        "uptime_seconds": uptime,
        "redis_connected": redis_ok,
        "background_tasks": len(_background_tasks),
    }
