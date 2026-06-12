"""Tests for agent-service security, validation, and API contracts."""


import socket
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from shared.utils.config import Settings
from shared.utils.network import (
    UnsafeTargetError,
    safe_async_request,
    validate_public_http_url,
)
from src.graphs.nodes.run_tests import _build_test_wrapper, _sandbox_python_runtime
from src.memory import MemoryManager
from src.memory.embeddings import EMBEDDING_DIMENSIONS, embed_text
from src.models import AgentRunRequest, SiteAnalysis
from src.validation import validate_generated_code, validate_records


class FakeMemory:
    async def healthcheck(self):
        return {"redis": False, "vector_store": False}

    async def save_human_feedback(self, *_args, **_kwargs):
        return None


@pytest_asyncio.fixture
async def client():
    from src.main import app

    app.state.memory_manager = FakeMemory()
    app.state.checkpoint_manager = SimpleNamespace(backend="memory", durable=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(client):
    assert (await client.get("/healthz")).status_code == 200
    ready = await client.get("/readyz")
    assert ready.status_code in {200, 503}
    assert "checkpoint_backend" in ready.json()


@pytest.mark.asyncio
async def test_run_rejects_missing_url(client):
    response = await client.post("/agent/run", json={"data_type": "articles"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_rejects_unresolvable_target(client, monkeypatch):
    async def fail_resolution(_url: str):
        raise UnsafeTargetError("Target hostname could not be resolved")

    monkeypatch.setattr("src.routers.agent.validate_public_http_url_async", fail_resolution)
    response = await client.post("/agent/run", json={"url": "https://does-not-exist.invalid"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "not-a-url"},
        {"url": "http://127.0.0.1:8000"},
        {"url": "https://example.com", "max_pages": 0},
        {"url": "https://example.com", "rate_limit_rps": -1},
    ],
)
def test_request_rejects_unsafe_or_unbounded_input(payload):
    with pytest.raises(ValidationError):
        AgentRunRequest(**payload)


def test_generated_code_policy_rejects_system_access():
    violations = validate_generated_code(
        "import os\n\ndef scrape(url, max_pages, rate_limit_rps):\n    return [os.environ]\n"
    )
    assert violations
    assert any("Import is not allowed" in violation for violation in violations)


def test_generated_code_policy_rejects_dynamic_introspection():
    violations = validate_generated_code(
        'def scrape(url, max_pages, rate_limit_rps):\n    return [getattr(object, "__subclasses__")]\n'
    )
    assert "Call is not allowed: getattr" in violations


def test_record_gate_enforces_required_fields():
    result = validate_records(
        [{"wrong": 1}],
        ["title", "url"],
        max_records=100,
        min_field_completeness=0.8,
    )
    assert result["status"] == "error"
    assert "completeness" in result["error"]


def test_record_gate_deduplicates_and_caps():
    result = validate_records(
        [{"title": "a"}, {"title": "a"}, {"title": "b"}],
        ["title"],
        max_records=2,
        min_field_completeness=1.0,
    )
    assert result["status"] == "success"
    assert result["metrics"]["record_count"] == 1


def test_wrapper_escapes_url_input():
    wrapper = _build_test_wrapper(
        "def scrape(url, max_pages, rate_limit_rps): return []",
        'https://example.com/"; injected = True; #',
        1,
    )
    compile(wrapper, "<wrapper>", "exec")


def test_site_analysis_schema_is_openai_strict_compatible():
    schema = SiteAnalysis.model_json_schema()
    object_schemas = [schema, *schema.get("$defs", {}).values()]

    for object_schema in object_schemas:
        assert object_schema["additionalProperties"] is False
        assert set(object_schema["required"]) == set(object_schema["properties"])


def test_sandbox_python_runtime_uses_mounted_paths():
    mounts, executable = _sandbox_python_runtime()

    assert executable.startswith("/runtime/python/bin/python")
    assert "/runtime/python" in mounts
    assert "/runtime/site-packages" in mounts
    assert executable != __import__("sys").executable


@pytest.mark.asyncio
async def test_safe_request_pins_validated_ip(monkeypatch):
    async def resolve(_url: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("shared.utils.network.resolve_public_http_url_async", resolve)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await safe_async_request(client, "GET", "https://example.com/path")
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_safe_request_rejects_redirect_outside_allowed_scope(monkeypatch):
    async def resolve(_url: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("shared.utils.network.resolve_public_http_url_async", resolve)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://other.example/path"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeTargetError, match="outside the allowed crawl scope"):
            await safe_async_request(
                client,
                "GET",
                "https://example.com/path",
                allowed_hosts={"example.com"},
            )


def test_public_url_validation_rejects_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(UnsafeTargetError):
        validate_public_http_url("https://example.com")


@pytest.mark.asyncio
async def test_memory_fallback_persists_feedback_and_errors():
    memory = MemoryManager(Settings(), redis_client=None)
    await memory.save_human_feedback("example.com", "Use article cards")
    await memory.save_error("example.com", "selector failed", "selector")
    assert (await memory.get_human_feedback("example.com"))[0]["feedback"] == "Use article cards"
    assert (await memory.get_known_errors("example.com"))[0]["error_type"] == "selector"


@pytest.mark.asyncio
async def test_feedback_endpoint(client):
    response = await client.post(
        "/agent/feedback",
        json={
            "domain": "example.com",
            "feedback": "Use .article",
            "feedback_type": "hint",
        },
    )
    assert response.status_code == 202


def test_embedding_is_deterministic_and_normalized():
    first = embed_text("example.com articles")
    second = embed_text("example.com articles")
    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert sum(value * value for value in first) == pytest.approx(1.0)
