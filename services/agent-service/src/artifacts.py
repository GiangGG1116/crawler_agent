"""Lifecycle management for generated crawler artifacts."""


import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.utils.config import Settings
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def promote_artifact(
    settings: Settings,
    *,
    request_id: str,
    domain: str,
    data_type: str,
    code: str,
    test_result: dict[str, Any],
) -> str:
    """Persist a validated crawler as an approved, reusable artifact."""
    approved_dir = settings.generated_crawlers_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = hashlib.sha256(f"{domain}:{data_type}".encode()).hexdigest()[:16]
    code_path = approved_dir / f"{artifact_id}.py"
    metadata_path = approved_dir / f"{artifact_id}.json"

    code_path.write_text(code, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "request_id": request_id,
                "domain": domain,
                "data_type": data_type,
                "approved_at": datetime.now(UTC).isoformat(),
                "test_result": test_result,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return str(code_path)


def cleanup_generated_artifacts(settings: Settings) -> int:
    """Delete stale unapproved generation directories."""
    root = settings.generated_crawlers_dir
    cutoff = datetime.now(UTC) - timedelta(hours=settings.agent_generated_artifact_ttl_hours)
    removed = 0
    for path in root.glob("sandbox_*"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            logger.warning("Failed to inspect generated artifact: %s", path)
    return removed
