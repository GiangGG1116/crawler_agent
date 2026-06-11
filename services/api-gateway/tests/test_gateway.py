"""Unit tests for api-gateway endpoints."""

from __future__ import annotations

import pytest


class TestHealthEndpoint:
    """Tests for GET /healthz."""

    def test_health_returns_ok(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "api-gateway"
        assert "uptime_seconds" in data
        assert "redis_connected" in data

    def test_health_includes_task_count(self, client):
        resp = client.get("/healthz")
        data = resp.json()
        assert "background_tasks" in data


class TestCrawlEndpoints:
    """Tests for /api/v1/crawl endpoints."""

    def test_submit_returns_202(self, client):
        resp = client.post(
            "/api/v1/crawl",
            json={
                "target": {"url": "https://example.com"},
                "data_spec": {"data_type": "articles"},
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "submitted"

    def test_submit_invalid_url_returns_400(self, client):
        resp = client.post(
            "/api/v1/crawl",
            json={
                "target": {"url": "not-a-url"},
                "data_spec": {"data_type": "articles"},
            },
        )
        assert resp.status_code == 400

    def test_status_not_found(self, client):
        resp = client.get("/api/v1/crawl/nonexistent-id/status")
        assert resp.status_code == 404

    def test_result_not_found(self, client):
        resp = client.get("/api/v1/crawl/nonexistent-id/result")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_status_after_submit(self, client, job_store):
        """After submitting a job, status should be available."""
        resp = client.post(
            "/api/v1/crawl",
            json={
                "target": {"url": "https://example.com"},
                "data_spec": {"data_type": "articles"},
            },
        )
        job_id = resp.json()["job_id"]

        status_resp = client.get(f"/api/v1/crawl/{job_id}/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["job_id"] == job_id
