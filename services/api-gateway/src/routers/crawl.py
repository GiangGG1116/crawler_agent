"""Crawl router — REST endpoints for crawl job management.

v2.0: Jobs run asynchronously. POST returns 202 Accepted with a job_id.
Clients poll GET /crawl/{id}/status for progress, GET /crawl/{id}/result
for the full result once completed.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from shared.models.request import CrawlRequest
from shared.utils.exceptions import CrawlValidationError
from shared.utils.logger import get_logger
from shared.utils.security import require_api_key

logger = get_logger(__name__)

router = APIRouter()


def _validate_url(url: str) -> None:
    """Basic URL validation."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise CrawlValidationError(
            message=f"Invalid URL: {url}",
            details="URL must include scheme (http/https) and domain",
        )
    if parsed.scheme not in ("http", "https"):
        raise CrawlValidationError(
            message=f"Unsupported URL scheme: {parsed.scheme}",
            details="Only http and https are supported",
        )


@router.post(
    "/crawl",
    status_code=202,
    dependencies=[Depends(require_api_key)],
    summary="Submit a new crawl job",
)
async def submit_crawl_job(
    crawl_request: CrawlRequest,
    request: Request,
):
    """Submit a crawl job. Returns 202 immediately with job_id.

    The pipeline runs in the background. Poll /crawl/{id}/status for progress.
    """
    _validate_url(crawl_request.target.url)

    job_store = request.app.state.job_store
    http_client = request.app.state.http_client

    # Create job in Redis
    job_data = await job_store.create_job(
        job_id=crawl_request.request_id,
        url=crawl_request.target.url,
        data_type=crawl_request.data_spec.data_type.value,
    )

    # Run pipeline in background
    from src.main import _background_tasks
    from src.services.job_router import JobRouter

    async def _run_pipeline():
        router_instance = JobRouter(http_client, job_store)
        try:
            result = await router_instance.execute(crawl_request)
            await job_store.complete_job(
                crawl_request.request_id,
                result.model_dump(mode="json"),
            )
        except Exception as e:
            logger.exception("Pipeline failed for %s", crawl_request.request_id)
            await job_store.fail_job(crawl_request.request_id, str(e))

    task = asyncio.create_task(_run_pipeline())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "job_id": crawl_request.request_id,
        "status": "submitted",
        "message": "Crawl job submitted. Poll /crawl/{id}/status for progress.",
    }


@router.get(
    "/crawl/{job_id}/status",
    summary="Get job status and progress",
)
async def get_job_status(job_id: str, request: Request):
    """Get current status and progress of a crawl job."""
    job_store = request.app.state.job_store
    status = await job_store.get_status(job_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return status


@router.get(
    "/crawl/{job_id}/result",
    summary="Get completed job result",
)
async def get_job_result(job_id: str, request: Request):
    """Get the full result of a completed crawl job."""
    job_store = request.app.state.job_store
    status = await job_store.get_status(job_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if status.get("status") == "running":
        return {
            "status": "running",
            "phase": status.get("phase"),
            "progress": status.get("progress"),
            "message": "Job is still running. Try again later.",
        }

    if status.get("status") == "failed":
        return {
            "status": "failed",
            "error": status.get("error", "Unknown error"),
        }

    result = await job_store.get_result(job_id)
    if not result:
        raise HTTPException(
            status_code=404, detail=f"Result for job {job_id} not found"
        )

    return result


@router.delete(
    "/crawl/{job_id}",
    summary="Delete a crawl job",
    dependencies=[Depends(require_api_key)],
)
async def delete_job(job_id: str, request: Request):
    """Delete a job and its result from Redis."""
    job_store = request.app.state.job_store
    deleted = await job_store.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"message": f"Job {job_id} deleted"}
