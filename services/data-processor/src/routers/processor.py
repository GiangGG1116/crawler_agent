"""Processor router — HTTP endpoints for Phase 3 data processing."""

from __future__ import annotations

from fastapi import APIRouter
from shared.models.audit import AuditLog
from shared.utils.logger import get_logger
from src.models.schemas import ProcessorResponse, ProcessRequest
from src.services.processor_service import ProcessorService

logger = get_logger(__name__)

router = APIRouter()


@router.post("/process", response_model=ProcessorResponse)
async def process_records(req: ProcessRequest):
    """Process raw crawl records: clean → validate → deduplicate → score → store."""
    logger.info(
        "Processing %d records for request %s", len(req.raw_records), req.request_id
    )

    service = ProcessorService()
    result = await service.process(req)
    return result


@router.post("/audit")
async def store_audit(audit: AuditLog):
    """Store an audit log record."""
    logger.info("Received audit log for request %s", audit.request_id)

    service = ProcessorService()
    await service.store_audit(audit)
    return {"status": "stored", "audit_id": audit.audit_id}
