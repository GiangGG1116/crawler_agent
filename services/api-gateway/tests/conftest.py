"""Pytest configuration for api-gateway tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.services.job_store import JobStore


class FakeRedis:
    """In-memory Redis mock for testing."""

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._ttl: dict[str, int] = {}

    async def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs):
        if key not in self._store:
            self._store[key] = {}
        if mapping:
            self._store[key].update(mapping)
        self._store[key].update(kwargs)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value
        if ex:
            self._ttl[key] = ex

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count

    async def expire(self, key: str, seconds: int):
        self._ttl[key] = seconds

    async def ping(self):
        return True

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def job_store(fake_redis):
    return JobStore(fake_redis)


@pytest.fixture
def app(fake_redis, job_store):
    """Create test application with mocked dependencies."""
    import httpx
    from src.main import app as _app

    _app.state.redis = fake_redis
    _app.state.job_store = job_store
    _app.state.http_client = httpx.AsyncClient()
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)
