"""Job Store — Redis-backed job state management.

Tracks crawl job lifecycle: submitted → running → phase updates → completed/failed.
Enables the async API pattern where POST returns immediately with a job_id,
and clients poll GET /status for progress.

Keys auto-expire after 24 hours.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from shared.utils.logger import get_logger

logger = get_logger(__name__)

JOB_TTL_SECONDS = 86400  # 24 hours


class JobPhase(str, Enum):
    """Phases in the crawl pipeline."""

    SUBMITTED = "submitted"
    PHASE0_ANALYSIS = "phase0_analysis"
    PHASE1_TEMPLATE = "phase1_template"
    PHASE2_AGENT = "phase2_agent"
    PHASE3_PROCESSING = "phase3_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStore:
    """Redis-backed job state store."""

    def __init__(self, redis_client):
        self._redis = redis_client

    def _status_key(self, job_id: str) -> str:
        return f"job:{job_id}:status"

    def _result_key(self, job_id: str) -> str:
        return f"job:{job_id}:result"

    async def create_job(
        self,
        job_id: str,
        url: str,
        data_type: str,
    ) -> dict[str, Any]:
        """Create a new job record in Redis."""
        now = datetime.now(UTC).isoformat()
        job_data = {
            "job_id": job_id,
            "status": "submitted",
            "phase": JobPhase.SUBMITTED.value,
            "progress": "0.0",
            "url": url,
            "data_type": data_type,
            "created_at": now,
            "updated_at": now,
        }
        await self._redis.hset(self._status_key(job_id), mapping=job_data)
        await self._redis.expire(self._status_key(job_id), JOB_TTL_SECONDS)
        logger.info("Job created: %s for %s", job_id, url)
        return job_data

    async def update_phase(
        self,
        job_id: str,
        phase: JobPhase,
        progress: float = 0.0,
    ) -> None:
        """Update job phase and progress."""
        now = datetime.now(UTC).isoformat()
        await self._redis.hset(
            self._status_key(job_id),
            mapping={
                "status": "running",
                "phase": phase.value,
                "progress": str(round(progress, 2)),
                "updated_at": now,
            },
        )
        logger.debug("Job %s → phase=%s progress=%.2f", job_id, phase.value, progress)

    async def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
    ) -> None:
        """Mark job as completed and store the result."""
        now = datetime.now(UTC).isoformat()
        await self._redis.hset(
            self._status_key(job_id),
            mapping={
                "status": "completed",
                "phase": JobPhase.COMPLETED.value,
                "progress": "1.0",
                "updated_at": now,
                "completed_at": now,
            },
        )
        await self._redis.set(
            self._result_key(job_id),
            json.dumps(result, default=str),
            ex=JOB_TTL_SECONDS,
        )
        logger.info("Job completed: %s", job_id)

    async def fail_job(
        self,
        job_id: str,
        error: str,
    ) -> None:
        """Mark job as failed with error message."""
        now = datetime.now(UTC).isoformat()
        await self._redis.hset(
            self._status_key(job_id),
            mapping={
                "status": "failed",
                "phase": JobPhase.FAILED.value,
                "error": error,
                "updated_at": now,
                "completed_at": now,
            },
        )
        logger.error("Job failed: %s — %s", job_id, error)

    async def get_status(self, job_id: str) -> dict[str, Any] | None:
        """Get current job status."""
        data = await self._redis.hgetall(self._status_key(job_id))
        if not data:
            return None
        # Convert progress to float
        if "progress" in data:
            data["progress"] = float(data["progress"])
        return data

    async def get_result(self, job_id: str) -> dict[str, Any] | None:
        """Get completed job result."""
        raw = await self._redis.get(self._result_key(job_id))
        if raw:
            return json.loads(raw)
        return None

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job and its result."""
        deleted = await self._redis.delete(
            self._status_key(job_id),
            self._result_key(job_id),
        )
        return deleted > 0
