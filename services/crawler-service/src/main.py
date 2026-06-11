"""Crawler Service — FastAPI application entry point.

Provides Phase 0 (site analysis) and Phase 1 (template crawling) endpoints.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting Crawler Service")
    yield
    logger.info("Crawler Service shutdown complete")


app = FastAPI(
    title="Agent Crawler — Crawler Service",
    version="1.0.0",
    description="Phase 0+1: Site analysis and template-based scraping",
    lifespan=lifespan,
)

register_exception_handlers(app)

from src.routers import crawl

app.include_router(crawl.router, prefix="/crawl", tags=["crawl"])


@app.get("/healthz", tags=["system"])
async def healthcheck():
    uptime = round(time.monotonic() - _start_time, 1)
    return {
        "status": "healthy",
        "service": "crawler-service",
        "uptime_seconds": uptime,
    }
