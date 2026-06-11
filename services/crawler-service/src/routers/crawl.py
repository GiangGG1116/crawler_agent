"""Crawl router — HTTP interface for Phase 0+1 pipeline.

This router is intentionally thin: it only handles HTTP I/O
(parse request → call service → return response).
All business logic lives in ``src.services.crawl_service.CrawlService``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from shared.utils.logger import get_logger
from src.models import CrawlerResponse
from src.services.crawl_service import CrawlService

logger = get_logger(__name__)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    url: str
    data_type: str = "articles"


@router.post("/analyze", response_model=dict)
async def analyze_site(req: AnalyzeRequest):
    """Phase 0: Analyze target website structure and detect web type."""
    service = CrawlService()
    analysis = await service.analyze(req.url, req.data_type)
    return analysis


@router.post("/execute", response_model=CrawlerResponse)
async def execute_crawl(request_data: dict[str, Any]):
    """Phase 1: Execute template-based crawl."""
    from shared.models.request import CrawlRequest

    crawl_request = CrawlRequest(**request_data)

    service = CrawlService()
    result = await service.execute(crawl_request)
    return result
