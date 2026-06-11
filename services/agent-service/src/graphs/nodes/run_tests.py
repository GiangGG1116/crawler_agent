"""Execute and validate generated crawler code in an isolated subprocess."""

import asyncio
import json
import os
import resource
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, HumanMessage
from shared.utils.config import get_settings
from shared.utils.logger import get_logger
from src.artifacts import promote_artifact
from src.validation import validate_generated_code, validate_records

logger = get_logger(__name__)

MAX_OUTPUT_BYTES = 1024 * 1024


async def run_crawler_tests(state: dict[str, Any]) -> dict[str, Any]:
    """Run generated code, then enforce schema and quality gates."""
    code = state.get("crawler_code", "")
    url = state["url"]
    attempt = state.get("attempt", 0)
    settings = get_settings()

    policy_errors = validate_generated_code(code)
    if policy_errors:
        error = "; ".join(policy_errors)
        return _failed_result(state, {"status": "error", "error": error}, error)

    logger.info("Running crawler tests for %s (attempt %d)", url, attempt + 1)
    wrapper = _build_test_wrapper(
        code,
        url,
        state.get("max_pages", 5),
        state.get("max_records", 1000),
        state.get("rate_limit_rps", 2.0),
    )
    execution = await _execute_sandboxed(wrapper, settings.agent_code_execution_timeout)
    if execution.get("status") != "success":
        error = execution.get("error", "Unknown sandbox error")
        return _failed_result(state, execution, error)

    validation = validate_records(
        execution.get("records", []),
        state.get("required_fields", []),
        max_records=state.get("max_records", 1000),
        min_field_completeness=settings.agent_min_field_completeness,
    )
    if validation["status"] != "success":
        return _failed_result(state, validation, validation["error"])

    records = validation["records"]
    test_result = {
        "status": "success",
        "record_count": len(records),
        "metrics": validation["metrics"],
        "sandbox_backend": settings.agent_sandbox_backend,
    }
    artifact_path = promote_artifact(
        settings,
        request_id=state.get("request_id", "unknown"),
        domain=urlparse(url).netloc,
        data_type=state.get("data_type", "unknown"),
        code=code,
        test_result=test_result,
    )
    logger.info("Crawler test passed: %d valid records from %s", len(records), url)
    return {
        "test_result": test_result,
        "records": records,
        "artifact_path": artifact_path,
        "messages": [
            HumanMessage(content=f"Run test for {url}"),
            AIMessage(content=f"Test passed: {len(records)} valid records"),
        ],
    }


def _failed_result(
    state: dict[str, Any], result: dict[str, Any], error: str
) -> dict[str, Any]:
    logger.warning("Crawler test failed: %s", error)
    return {
        "test_result": result,
        "records": [],
        "errors": state.get("errors", []) + [f"Test failed: {error}"],
        "messages": [
            HumanMessage(content=f"Test failed for {state.get('url')}"),
            AIMessage(content=f"Error: {error}"),
        ],
    }


def _build_test_wrapper(
    crawler_code: str,
    url: str,
    max_pages: int,
    max_records: int = 1000,
    rate_limit_rps: float = 2.0,
) -> str:
    """Wrap generated code without interpolating unescaped user input."""
    max_processes = get_settings().agent_sandbox_max_processes
    return f"""
import asyncio
import ipaddress
import json
import resource as _sandbox_resource
import socket
from urllib.parse import urlparse

_sandbox_resource.setrlimit(_sandbox_resource.RLIMIT_NPROC, ({max_processes!r}, {max_processes!r}))
del _sandbox_resource

_target_host = urlparse({url!r}).hostname
_original_getaddrinfo = socket.getaddrinfo

def _safe_getaddrinfo(host, *args, **kwargs):
    normalized = str(host).rstrip(".").lower()
    if normalized != _target_host and not normalized.endswith("." + _target_host):
        raise OSError("Outbound host is outside the approved crawl scope")
    results = _original_getaddrinfo(host, *args, **kwargs)
    for result in results:
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise OSError("Outbound target resolved to a non-public address")
    return results

socket.getaddrinfo = _safe_getaddrinfo

{crawler_code}

async def _test_main():
    try:
        if asyncio.iscoroutinefunction(scrape):
            records = await scrape({url!r}, max_pages={max_pages!r}, rate_limit_rps={rate_limit_rps!r})
        else:
            records = scrape({url!r}, max_pages={max_pages!r}, rate_limit_rps={rate_limit_rps!r})
        if not isinstance(records, list):
            records = list(records) if records else []
        output = {{"status": "success", "records": records[:{max_records!r}], "record_count": len(records)}}
    except Exception as exc:
        output = {{"status": "error", "error": str(exc), "error_type": type(exc).__name__}}
    print("__RESULT__" + json.dumps(output, default=str))

asyncio.run(_test_main())
"""


def _resource_limiter() -> None:
    settings = get_settings()
    memory_bytes = settings.agent_sandbox_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (settings.agent_sandbox_cpu_seconds, settings.agent_sandbox_cpu_seconds),
    )
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    os.setsid()


def _sandbox_command(code_path: Path, tmpdir: str) -> list[str]:
    settings = get_settings()
    if settings.agent_sandbox_backend != "bubblewrap":
        if settings.app_env.lower() == "production":
            raise RuntimeError("Production requires AGENT_SANDBOX_BACKEND=bubblewrap")
        return [sys.executable, str(code_path)]

    bwrap = shutil.which("bwrap")
    if not bwrap:
        if settings.app_env.lower() == "production":
            raise RuntimeError("Bubblewrap is required but is not installed")
        logger.warning("Bubblewrap unavailable; using development subprocess fallback")
        return [sys.executable, str(code_path)]

    launcher = Path("/usr/local/bin/agent-sandbox-launcher")
    if launcher.is_file():
        return [str(launcher), str(code_path)]

    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/etc",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
    ]
    if Path("/lib64").exists():
        command += ["--ro-bind", "/lib64", "/lib64"]
    for path in ("/etc/ssl", "/etc/resolv.conf", "/etc/hosts"):
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    command += [
        "--ro-bind",
        tmpdir,
        "/sandbox",
        "--tmpfs",
        "/tmp",  # noqa: S108 - isolated tmpfs inside the Bubblewrap namespace
        "--chdir",
        "/sandbox",
        "--setenv",
        "HOME",
        "/tmp",  # noqa: S108 - isolated tmpfs inside the Bubblewrap namespace
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        sys.executable,
        f"/sandbox/{code_path.name}",
    ]
    return command


async def _execute_sandboxed(code: str, timeout: int) -> dict[str, Any]:
    """Run code with resource limits, bounded output, and filesystem isolation."""
    with tempfile.TemporaryDirectory(prefix="agent-sandbox-") as tmpdir:
        code_path = Path(tmpdir) / "runner.py"
        stdout_path = Path(tmpdir) / "stdout.log"
        stderr_path = Path(tmpdir) / "stderr.log"
        code_path.write_text(code, encoding="utf-8")
        code_path.chmod(0o600)
        safe_env = {
            key: value
            for key, value in os.environ.items()
            if not any(
                secret in key.upper()
                for secret in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
            )
            and not key.upper().endswith("_PROXY")
            and key.upper() != "NO_PROXY"
        }

        try:
            command = _sandbox_command(code_path, tmpdir)
            with stdout_path.open("wb") as stdout_file, stderr_path.open(
                "wb"
            ) as stderr_file:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=tmpdir,
                    env=safe_env,
                    preexec_fn=_resource_limiter,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout)
                except TimeoutError:
                    os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
                    return {
                        "status": "timeout",
                        "error": f"Execution exceeded {timeout}s timeout",
                    }

            stdout_text = stdout_path.read_text(errors="replace")[:MAX_OUTPUT_BYTES]
            stderr_text = stderr_path.read_text(errors="replace")[:MAX_OUTPUT_BYTES]
            if "__RESULT__" in stdout_text:
                return json.loads(stdout_text.rsplit("__RESULT__", 1)[1].strip())
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "error": stderr_text or f"Exit code {proc.returncode}",
                }
            return {"status": "error", "error": "No result marker found in output"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
