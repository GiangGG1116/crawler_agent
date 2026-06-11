"""ProcessorService — orchestrates the Phase 3 data processing pipeline.

Pipeline: raw data → clean → validate → deduplicate → score → store
"""

from __future__ import annotations

from shared.models.audit import AuditLog
from shared.utils.config import get_settings
from shared.utils.logger import get_logger
from src.models.schemas import ProcessorResponse, ProcessRequest
from src.processing.cleaner import DataCleaner
from src.processing.deduplicator import Deduplicator
from src.processing.scorer import QualityScorer
from src.processing.storage import DataStorage
from src.processing.validator import SchemaValidator

logger = get_logger(__name__)


class ProcessorService:
    """Orchestrates the full data processing pipeline."""

    def __init__(self):
        self._settings = get_settings()
        self._cleaner = DataCleaner()
        self._validator = SchemaValidator()
        self._deduplicator = Deduplicator()
        self._scorer = QualityScorer()
        self._storage = DataStorage(self._settings)

    async def process(self, request: ProcessRequest) -> ProcessorResponse:
        """Run the full processing pipeline on raw records."""
        raw_records = request.raw_records
        logger.info(
            "Processing %d raw records for %s", len(raw_records), request.request_id
        )

        try:
            # Step 1: Clean
            cleaned = self._cleaner.clean(raw_records)
            logger.info("Cleaned: %d → %d records", len(raw_records), len(cleaned))

            # Step 2: Validate
            valid, invalid = self._validator.validate(
                cleaned,
                request.required_fields,
                request.optional_fields,
            )
            logger.info("Validated: %d valid, %d invalid", len(valid), len(invalid))

            # Step 3: Deduplicate
            unique = self._deduplicator.deduplicate(valid)
            logger.info("Deduplicated: %d → %d records", len(valid), len(unique))

            # Step 4: Score
            quality = self._scorer.score(
                raw_count=len(raw_records),
                clean_count=len(unique),
                rejected_count=len(invalid),
                required_fields=request.required_fields,
                records=unique,
            )

            # Step 5: Store
            output_path = await self._storage.store(
                request_id=request.request_id,
                records=unique,
                output_format=request.output_format,
                output_destination=request.output_destination,
            )

            return ProcessorResponse(
                status="success",
                clean_records=unique,
                rejected_records=invalid,
                quality_report=quality.model_dump(),
                output_path=output_path,
            )

        except Exception as e:
            logger.exception("Processing failed: %s", e)
            return ProcessorResponse(
                status="failed",
                errors=[str(e)],
            )

    async def store_audit(self, audit: AuditLog) -> None:
        """Persist an audit log to storage."""
        try:
            await self._storage.store_audit(audit)
        except Exception as e:
            logger.error("Audit storage failed: %s", e)
