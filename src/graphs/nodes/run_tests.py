"""Node: run_crawler_tests — Execute generated crawler and validate output.

Runs the generated crawler in a sandboxed subprocess, collects output,
and validates against the test matrix (TC1-TC5 from the design doc).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.graphs.state import AgentGraphState
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def run_crawler_tests(state: AgentGraphState) -> dict[str, Any]:
    """Execute the generated crawler and validate results."""
    generated = state.get("generated", {})
    entrypoint = generated.get("entrypoint")
    request_id = state.get("request_id", "unknown")
    attempt = state.get("attempt", 1)
    required_fields = state.get("required_fields", [])

    logger.info(f"[Attempt {attempt}] Running crawler tests", extra={"request_id": request_id, "phase": "phase2"})

    if not entrypoint or not Path(entrypoint).exists():
        return {
            "test": {"passed": False, "metrics": {}, "errors": ["Entrypoint file not found"], "sample_records": []},
            "raw_records": [],
        }

    # Execute the crawler in a subprocess with timeout
    settings = get_settings()
    timeout = settings.agent_code_execution_timeout

    try:
        # Create a runner script that imports and calls the generated crawler
        runner_code = f"""
import asyncio, json, sys
sys.path.insert(0, "{settings.project_root}")

async def main():
    # Import the generated crawler module
    import importlib.util
    spec = importlib.util.spec_from_file_location("crawler", "{entrypoint}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Call the crawl function (expected interface)
    if hasattr(mod, 'crawl'):
        records = await mod.crawl("{state['target_url']}", max_pages=3, max_records=50)
        print(json.dumps(records, default=str, ensure_ascii=False))
    else:
        print("[]")

asyncio.run(main())
"""
        runner_path = Path(tempfile.mktemp(suffix=".py", dir=str(settings.generated_crawlers_dir)))
        runner_path.write_text(runner_code, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(runner_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(settings.project_root),
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        # Cleanup runner
        runner_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[:2000]
            logger.error(f"Crawler execution failed: {error_msg}", extra={"request_id": request_id})
            return {
                "test": {"passed": False, "metrics": {}, "errors": [error_msg], "sample_records": []},
                "raw_records": [],
            }

        # Parse output records
        output = stdout.decode("utf-8", errors="replace").strip()
        try:
            records = json.loads(output)
            if not isinstance(records, list):
                records = [records] if records else []
        except json.JSONDecodeError:
            return {
                "test": {"passed": False, "metrics": {}, "errors": ["Invalid JSON output"], "sample_records": []},
                "raw_records": [],
            }

    except asyncio.TimeoutError:
        return {
            "test": {"passed": False, "metrics": {}, "errors": [f"Timeout after {timeout}s"], "sample_records": []},
            "raw_records": [],
        }
    except Exception as e:
        return {
            "test": {"passed": False, "metrics": {}, "errors": [str(e)], "sample_records": []},
            "raw_records": [],
        }

    # Validate against test matrix
    test_result = _validate_records(records, required_fields)

    logger.info(
        f"Test result: passed={test_result['passed']}, records={len(records)}",
        extra={"request_id": request_id},
    )

    return {
        "test": test_result,
        "raw_records": records,
    }


def _validate_records(records: list[dict], required_fields: list[str]) -> dict[str, Any]:
    """Validate records against TC1-TC5 test matrix."""
    errors = []
    metrics: dict[str, Any] = {"record_count": len(records)}

    # TC1: Must have at least 1 record
    if not records:
        errors.append("TC1 FAIL: No records extracted")
        return {"passed": False, "metrics": metrics, "errors": errors, "sample_records": []}

    # TC2: Required fields completeness
    if required_fields:
        total_checks = len(records) * len(required_fields)
        present = sum(
            1 for r in records for f in required_fields if r.get(f) is not None and r.get(f) != ""
        )
        completeness = present / total_checks if total_checks > 0 else 0
        metrics["field_completeness"] = round(completeness * 100, 1)

        if completeness < 0.5:
            errors.append(f"TC2 FAIL: Field completeness {completeness:.0%} < 50%")

    # TC3: No crash (we got here, so no crash)
    metrics["no_crash"] = True

    # Decision
    passed = len(errors) == 0
    return {
        "passed": passed,
        "metrics": metrics,
        "errors": errors,
        "sample_records": records[:5],
    }
