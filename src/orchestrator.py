"""CrawlOrchestrator — main entry point for crawl jobs.

Coordinates the full pipeline: Phase 0 → Phase 1 → Phase 2 (fallback) → Phase 3.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from src.analyzer import WebAnalyzer
from src.graphs.custom_agent_graph import CustomAgentGraphRunner
from src.models.audit import AuditLog
from src.models.request import CrawlRequest
from src.models.result import (
    CrawlResult,
    CrawlStatus,
    PhaseUsed,
    TemplateFailure,
)
from src.processing.cleaner import DataCleaner
from src.processing.deduplicator import Deduplicator
from src.processing.scorer import QualityScorer
from src.processing.storage import DataStorage
from src.processing.validator import SchemaValidator
from src.templates.registry import TemplateRegistry
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CrawlOrchestrator:
    """
    Main orchestrator for crawl jobs.

    Flow:
    1. Phase 0: Analyze URL and classify web type
    2. Phase 1: Try template fast path
    3. Phase 2: Fall back to AI agent if template fails
    4. Phase 3: Clean, validate, and store data
    """

    def __init__(self):
        self.settings = get_settings()
        self.analyzer = WebAnalyzer()
        self.template_registry = TemplateRegistry()
        self.agent_runner = CustomAgentGraphRunner()
        self.validator = SchemaValidator()
        self.cleaner = DataCleaner()
        self.deduplicator = Deduplicator()
        self.scorer = QualityScorer()
        self.storage = DataStorage()

        # Auto-register built-in templates
        self.template_registry.auto_register(self.settings.templates_config_dir)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        """Execute a full crawl job."""
        start_time = time.monotonic()
        started_at = datetime.now(timezone.utc)

        result = CrawlResult(request_id=request.request_id, status=CrawlStatus.RUNNING, started_at=started_at)
        audit = AuditLog(request_id=request.request_id, source_url=request.target.url)

        logger.info(f"Starting crawl job: {request.target.url}", extra={"request_id": request.request_id})

        try:
            # ── PHASE 0: Input Analysis ──────────────────────────────────
            audit.add_event("phase0", "start", "Analyzing target URL")
            analysis = await self.analyzer.analyze(request)
            audit.add_event("phase0", "complete", f"Classified as {request.target.web_type.value}")

            self.cleaner.base_url = request.target.url

            # ── PHASE 1: Template Fast Path ──────────────────────────────
            raw_records = await self._try_template(request, result, audit)

            # ── PHASE 2: Custom Agent (if template failed) ───────────────
            if raw_records is None:
                raw_records = await self._run_custom_agent(request, result, audit)

            # ── PHASE 3: Data Processing ─────────────────────────────────
            if raw_records:
                result = await self._process_data(raw_records, request, result, audit, started_at)
            else:
                result.status = CrawlStatus.FAILED
                result.errors.append("No records extracted from any phase")

        except Exception as e:
            logger.error(f"Crawl job failed: {e}", extra={"request_id": request.request_id})
            result.status = CrawlStatus.FAILED
            result.errors.append(str(e))

        # Finalize
        duration = time.monotonic() - start_time
        result.duration_seconds = round(duration, 2)
        result.completed_at = datetime.now(timezone.utc)

        audit.finalize(
            status=result.status,
            phase_used=result.phase_used or PhaseUsed.TEMPLATE,
            records_raw=len(result.raw_records),
            records_clean=len(result.clean_records),
            records_rejected=len(result.rejected_records),
            quality_score=result.quality.overall_score if result.quality else 0,
            duration_seconds=result.duration_seconds,
        )

        # Save audit log
        try:
            self.storage.save_audit(audit.model_dump(), request.request_id)
        except Exception as e:
            logger.warning(f"Failed to save audit log: {e}")

        logger.info(
            f"Crawl complete: status={result.status.value}, records={len(result.clean_records)}, "
            f"quality={result.quality.overall_score if result.quality else 0:.1f}%, duration={duration:.1f}s",
            extra={"request_id": request.request_id},
        )
        return result

    async def _try_template(
        self, request: CrawlRequest, result: CrawlResult, audit: AuditLog,
    ) -> list[dict[str, Any]] | None:
        """Phase 1: Try template fast path. Returns records or None on failure."""
        audit.add_event("phase1", "start", "Attempting template fast path")

        try:
            template, config = self.template_registry.lookup(
                request.target.web_type,
                request.data_spec.data_type,
            )
            result.template_id = template.template_id
            audit.add_event("phase1", "template_found", f"Using {template.template_id}")

            raw_records = await template.run(request, config)

            # Gate check validation
            validation = self.validator.validate(raw_records, request)
            result.validation = validation

            if validation.is_valid:
                result.phase_used = PhaseUsed.TEMPLATE
                result.attempts = 1
                audit.add_event("phase1", "pass", f"Template succeeded: {len(raw_records)} records")
                return raw_records
            else:
                result.template_failure = TemplateFailure(
                    template_id=template.template_id,
                    reason=validation.decision_reason,
                    error_log_excerpt="; ".join(template.errors[:3]),
                )
                audit.add_event("phase1", "fail", f"Validation failed: {validation.decision_reason}")
                return None

        except KeyError as e:
            audit.add_event("phase1", "skip", f"No template for web type: {e}")
            result.template_failure = TemplateFailure(reason=f"No template: {e}")
            return None
        except Exception as e:
            audit.add_event("phase1", "error", f"Template error: {e}")
            result.template_failure = TemplateFailure(reason=str(e))
            return None

    async def _run_custom_agent(
        self, request: CrawlRequest, result: CrawlResult, audit: AuditLog,
    ) -> list[dict[str, Any]] | None:
        """Phase 2: Run LangGraph custom agent workflow."""
        audit.add_event("phase2", "start", "Starting custom agent workflow")

        try:
            tf = result.template_failure
            graph_result = await self.agent_runner.run(
                request_id=request.request_id,
                target_url=request.target.url,
                web_type=request.target.web_type.value if request.target.web_type else "STATIC",
                required_fields=request.data_spec.required_fields,
                template_failure=tf.model_dump() if tf else None,
                rate_limit_rps=request.constraints.rate_limit_rps,
                max_pages=request.scope.max_pages,
                max_records=request.scope.max_records,
            )

            decision = graph_result.get("decision", "alert_human")
            raw_records = graph_result.get("raw_records", [])
            result.attempts = graph_result.get("attempt", 1)

            if decision == "pass" and raw_records:
                result.phase_used = PhaseUsed.CUSTOM_AGENT
                audit.add_event("phase2", "pass", f"Agent succeeded: {len(raw_records)} records")
                return raw_records
            else:
                audit.add_event("phase2", "fail", f"Agent decision: {decision}")
                return None

        except Exception as e:
            logger.error(f"Custom agent failed: {e}", extra={"request_id": request.request_id})
            audit.add_event("phase2", "error", str(e))
            return None

    async def _process_data(
        self,
        raw_records: list[dict[str, Any]],
        request: CrawlRequest,
        result: CrawlResult,
        audit: AuditLog,
        started_at: datetime,
    ) -> CrawlResult:
        """Phase 3: Clean, deduplicate, score, and store data."""
        audit.add_event("phase3", "start", f"Processing {len(raw_records)} raw records")
        result.raw_records = raw_records

        # Clean
        clean_records = self.cleaner.clean_records(raw_records)

        # Deduplicate
        dedup_key_fields = request.data_spec.required_fields or None
        self.deduplicator.key_fields = dedup_key_fields
        clean_records, dupes_removed = self.deduplicator.deduplicate(clean_records)

        result.clean_records = clean_records
        result.rejected_records = [r for r in raw_records if r not in clean_records]

        # Quality scoring
        quality = self.scorer.score(
            clean_records=clean_records,
            total_before_dedup=len(raw_records),
            required_fields=request.data_spec.required_fields,
            crawl_timestamp=started_at,
        )
        result.quality = quality

        # Save data
        try:
            output_path = self.storage.save(
                records=clean_records,
                request_id=request.request_id,
                format=request.output.format,
                destination=request.output.destination,
            )
            result.output_path = output_path
        except Exception as e:
            logger.warning(f"Storage save failed, saving locally: {e}")
            from src.models.request import OutputDestination
            output_path = self.storage.save(
                records=clean_records,
                request_id=request.request_id,
                format=request.output.format,
                destination=OutputDestination.LOCAL_FILE,
            )
            result.output_path = output_path

        # Set final status based on quality grade
        if quality.overall_score >= 70:
            result.status = CrawlStatus.SUCCESS
        elif quality.overall_score >= 50:
            result.status = CrawlStatus.PARTIAL
        else:
            result.status = CrawlStatus.PARTIAL

        audit.add_event(
            "phase3", "complete",
            f"Quality={quality.overall_score:.1f}% ({quality.grade.value}), saved to {result.output_path}",
        )
        return result
