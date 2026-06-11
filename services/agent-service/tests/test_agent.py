"""Tests for agent-service security, validation, and API contracts."""

from __future__ import annotations

import socket

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from shared.utils.config import Settings
from shared.utils.network import (
    UnsafeTargetError,
    safe_async_request,
    validate_public_http_url,
)
from src.graphs.nodes.run_tests import _build_test_wrapper
from src.memory import MemoryManager
from src.memory.embeddings import EMBEDDING_DIMENSIONS, embed_text
from src.models import AgentRunRequest
from src.validation import validate_generated_code, validate_records


@pytest.fixture
def client():
    from src.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_and_readiness_endpoints(client):
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code in {200, 503}
    assert "checkpoint_backend" in ready.json()


def test_run_rejects_missing_url(client):
    assert client.post("/agent/run", json={"data_type": "articles"}).status_code == 422


def test_run_rejects_unresolvable_target(client):
    response = client.post("/agent/run", json={"url": "https://does-not-exist.invalid"})
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


@pytest.mark.asyncio
async def test_safe_request_pins_validated_ip(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await safe_async_request(client, "GET", "https://example.com/path")
    assert response.text == "ok"


def test_public_url_validation_rejects_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(UnsafeTargetError):
        validate_public_http_url("https://example.com")


@pytest.mark.asyncio
async def test_memory_fallback_persists_feedback_and_errors():
    memory = MemoryManager(Settings(), redis_client=None)
    await memory.save_human_feedback("example.com", "Use article cards")
    await memory.save_error("example.com", "selector failed", "selector")
    assert (await memory.get_human_feedback("example.com"))[0][
        "feedback"
    ] == "Use article cards"
    assert (await memory.get_known_errors("example.com"))[0]["error_type"] == "selector"


def test_feedback_endpoint(client):
    response = client.post(
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
