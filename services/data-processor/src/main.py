"""Data Processor Service — FastAPI application entry point.

Phase 3: clean, validate, deduplicate, score, and store crawl data.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from shared.utils.config import get_settings
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting Data Processor Service")
    yield
    logger.info("Data Processor Service shutdown complete")


app = FastAPI(
    title="Agent Crawler — Data Processor",
    version="1.0.0",
    description="Phase 3: Data cleaning, deduplication, quality scoring, and storage",
    lifespan=lifespan,
)

register_exception_handlers(app)

from src.routers import processor

app.include_router(processor.router, tags=["processor"])


@app.get("/healthz", tags=["system"])
async def healthcheck():
    settings = get_settings()
    uptime = round(time.monotonic() - _start_time, 1)
    return {
        "status": "healthy",
        "service": "data-processor",
        "uptime_seconds": uptime,
        "minio_endpoint": settings.minio_endpoint,
    }
