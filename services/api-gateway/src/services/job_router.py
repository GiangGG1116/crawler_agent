"""Job Router — orchestrates calls across microservices.

Each phase is a remote HTTP call with retry logic. Progress is tracked
in Redis via the JobStore so clients can poll for status.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
from shared.models.audit import AuditLog
from shared.models.request import CrawlRequest
from shared.models.result import CrawlResult, CrawlStatus, PhaseUsed
from shared.utils.config import get_settings
from shared.utils.logger import get_logger
from src.services.job_store import JobPhase, JobStore
from src.services.service_caller import ServiceCaller

logger = get_logger(__name__)

# Quality threshold — skip processor if quality is already high from templates
QUALITY_THRESHOLD = 70.0


class JobRouter:
    """Orchestrate the multi-phase crawl pipeline across services."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        job_store: JobStore,
    ):
        self._caller = ServiceCaller(http_client)
        self._job_store = job_store
        self._settings = get_settings()

    async def execute(self, request: CrawlRequest) -> CrawlResult:
        """Run the full pipeline: Phase 0 → Phase 1 → Phase 2 (if needed) → Phase 3."""
        request_id = request.request_id
        start_time = time.monotonic()
        result = CrawlResult(request_id=request_id)
        result.status = CrawlStatus.RUNNING
        result.started_at = datetime.now(UTC)

        # Audit trail
        audit = AuditLog(
            request_id=request_id,
            source_url=request.target.url,
        )
        audit.add_event(
            "start", "submitted", f"Crawl job started for {request.target.url}"
        )

        try:
            # === Phase 0: Site Analysis ===
            await self._job_store.update_phase(
                request_id, JobPhase.PHASE0_ANALYSIS, 0.1
            )
            audit.add_event("phase0", "start", "Analyzing target site")

            analysis = await self._call_analyzer(request)
            if analysis:
                result.detected_web_type = analysis.get("web_type")
                audit.add_event(
                    "phase0", "pass", f"Web type: {result.detected_web_type}"
                )

            # === Phase 1: Template Crawling ===
            await self._job_store.update_phase(
                request_id, JobPhase.PHASE1_TEMPLATE, 0.3
            )
            audit.add_event("phase1", "start", "Attempting template crawl")

            crawler_result = await self._call_crawler(request)
            raw_records = crawler_result.get("records", [])
            if raw_records:
                result.raw_records = raw_records
                result.phase_used = PhaseUsed.TEMPLATE
                audit.add_event(
                    "phase1", "pass", f"Template succeeded: {len(raw_records)} records"
                )
            else:
                # === Phase 2: Agent (fallback) ===
                await self._job_store.update_phase(
                    request_id, JobPhase.PHASE2_AGENT, 0.5
                )
                audit.add_event("phase2", "start", "Escalating to AI agent")

                agent_result = await self._call_agent(
                    request,
                    analysis=analysis,
                    template_failure={
                        "status": crawler_result.get("status"),
                        "errors": crawler_result.get("errors", []),
                        "failures": crawler_result.get("failures", []),
                    },
                )
                if agent_result and agent_result.get("status") == "success":
                    raw_records = agent_result.get("records", [])
                    result.raw_records = raw_records
                    result.phase_used = PhaseUsed.CUSTOM_AGENT
                    audit.add_event(
                        "phase2", "pass", f"Agent succeeded: {len(raw_records)} records"
                    )
                else:
                    result.status = CrawlStatus.FAILED
                    result.errors.append("Both template and agent phases failed")
                    audit.add_event("phase2", "fail", "Agent failed after max retries")

            # === Phase 3: Data Processing ===
            if result.raw_records:
                await self._job_store.update_phase(
                    request_id, JobPhase.PHASE3_PROCESSING, 0.7
                )
                audit.add_event("phase3", "start", "Processing data")

                processed = await self._call_processor(request, result.raw_records)
                if processed:
                    result.clean_records = processed.get("clean_records", [])
                    result.rejected_records = processed.get("rejected_records", [])
                    result.output_path = processed.get("output_path")

                    quality = processed.get("quality_report")
                    if quality:
                        from shared.models.result import QualityReport

                        result.quality = QualityReport(**quality)

                    result.status = CrawlStatus.SUCCESS
                    audit.add_event(
                        "phase3", "pass", f"Clean: {len(result.clean_records)} records"
                    )
                else:
                    # Processing failed but we still have raw data
                    result.status = CrawlStatus.PARTIAL
                    audit.add_event(
                        "phase3", "fail", "Processing failed, raw data available"
                    )

            # Finalize
            result.duration_seconds = round(time.monotonic() - start_time, 2)
            result.completed_at = datetime.now(UTC)
            if result.status == CrawlStatus.RUNNING:
                result.status = (
                    CrawlStatus.SUCCESS if result.raw_records else CrawlStatus.FAILED
                )

        except Exception as e:
            logger.exception("Pipeline error for %s: %s", request_id, e)
            result.status = CrawlStatus.FAILED
            result.errors.append(str(e))
            result.duration_seconds = round(time.monotonic() - start_time, 2)
            result.completed_at = datetime.now(UTC)
            audit.add_event("error", "exception", str(e))

        finally:
            # Persist audit log (never crash the main job)
            audit.finalize(
                status=result.status,
                phase_used=result.phase_used or PhaseUsed.TEMPLATE,
                records_raw=len(result.raw_records),
                records_clean=len(result.clean_records),
                records_rejected=len(result.rejected_records),
                quality_score=result.quality.overall_score if result.quality else 0.0,
                duration_seconds=result.duration_seconds,
            )
            await self._persist_audit(audit)

        return result

    # ── Service Calls ────────────────────────────────────────────────────────

    async def _call_analyzer(self, request: CrawlRequest) -> dict[str, Any] | None:
        """Phase 0: Call crawler-service to analyze the target site."""
        try:
            url = f"{self._settings.crawler_service_url}/crawl/analyze"
            resp = await self._caller.post(
                url,
                json_data={
                    "url": request.target.url,
                    "data_type": request.data_spec.data_type.value,
                },
            )
            return resp.json()
        except Exception as e:
            logger.warning("Phase 0 analysis failed: %s", e)
            return None

    async def _call_crawler(self, request: CrawlRequest) -> dict[str, Any]:
        """Phase 1: Call crawler-service to execute template crawl."""
        try:
            url = f"{self._settings.crawler_service_url}/crawl/execute"
            resp = await self._caller.post(
                url, json_data=request.model_dump(mode="json")
            )
            data = resp.json()
            return data
        except Exception as e:
            logger.warning("Phase 1 template crawl failed: %s", e)
            return {"status": "failed", "records": [], "errors": [str(e)]}

    async def _call_agent(
        self,
        request: CrawlRequest,
        *,
        analysis: dict[str, Any] | None,
        template_failure: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Phase 2: Call agent-service to generate custom crawler."""
        try:
            url = f"{self._settings.agent_service_url}/agent/run"
            resp = await self._caller.post(
                url,
                json_data={
                    "request_id": request.request_id,
                    "url": request.target.url,
                    "data_type": request.data_spec.data_type.value,
                    "required_fields": request.data_spec.required_fields,
                    "max_pages": request.scope.max_pages,
                    "max_records": request.scope.max_records,
                    "rate_limit_rps": request.constraints.rate_limit_rps,
                    "timeout_seconds": request.constraints.timeout_seconds,
                    "respect_robots_txt": request.constraints.respect_robots_txt,
                    "initial_analysis": analysis,
                    "template_failure": template_failure,
                },
                timeout=600,
            )
            return resp.json()
        except Exception as e:
            logger.warning("Phase 2 agent failed: %s", e)
            return None

    async def _call_processor(
        self,
        request: CrawlRequest,
        raw_records: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Phase 3: Call data-processor to clean and score data."""
        try:
            url = f"{self._settings.processor_service_url}/process"
            resp = await self._caller.post(
                url,
                json_data={
                    "request_id": request.request_id,
                    "source_url": request.target.url,
                    "raw_records": raw_records,
                    "required_fields": request.data_spec.required_fields,
                    "optional_fields": request.data_spec.optional_fields,
                    "output_format": request.output.format.value,
                    "output_destination": request.output.destination.value,
                },
            )
            return resp.json()
        except Exception as e:
            logger.warning("Phase 3 processing failed: %s", e)
            return None

    async def _persist_audit(self, audit: AuditLog) -> None:
        """Persist audit log to data-processor (non-critical)."""
        try:
            url = f"{self._settings.processor_service_url}/audit"
            await self._caller.fire_and_forget(
                "POST",
                url,
                json_data=audit.model_dump(mode="json"),
            )
        except Exception as e:
            logger.warning("Audit persistence failed (non-critical): %s", e)
