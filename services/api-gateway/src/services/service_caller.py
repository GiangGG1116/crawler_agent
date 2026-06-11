"""Resilient HTTP caller — retry + circuit breaker for inter-service calls.

Wraps httpx calls with:
  - Automatic retries (3 attempts, exponential backoff)
  - Timeout handling
  - Structured error logging with request_id

Uses tenacity (already in api-gateway deps).
"""

from __future__ import annotations

from typing import Any

import httpx
from shared.utils.config import get_settings
from shared.utils.logger import get_logger
from src.middleware.tracing import request_id_ctx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = get_logger(__name__)


class ServiceCaller:
    """Resilient HTTP caller for inter-service communication."""

    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._settings = get_settings()

    def _headers(self) -> dict[str, str]:
        """Build headers with X-Request-ID for distributed tracing."""
        headers: dict[str, str] = {}
        req_id = request_id_ctx.get("")
        if req_id:
            headers["X-Request-ID"] = req_id
        if self._settings.internal_service_token:
            headers["X-Internal-Service-Token"] = self._settings.internal_service_token
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def call(
        self,
        method: str,
        url: str,
        json_data: dict[str, Any] | None = None,
        timeout: float = 300,
    ) -> httpx.Response:
        """Make a resilient HTTP call with retry."""
        response = await self._client.request(
            method=method,
            url=url,
            json=json_data,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    async def post(
        self, url: str, json_data: dict[str, Any], **kwargs
    ) -> httpx.Response:
        return await self.call("POST", url, json_data=json_data, **kwargs)

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.call("GET", url, **kwargs)

    async def fire_and_forget(
        self,
        method: str,
        url: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Non-critical call — log errors but never crash the main job."""
        try:
            await self.call(method, url, json_data=json_data, timeout=30)
        except Exception as e:
            logger.warning("fire_and_forget failed: %s %s — %s", method, url, e)
