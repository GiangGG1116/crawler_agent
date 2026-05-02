"""HTTP client — shared utilities for making web requests.

Provides retry logic, rate limiting, User-Agent rotation, and proxy support.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.proxy import ProxyRotator

logger = get_logger(__name__)

# Common browser User-Agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


class RateLimiter:
    """Token-bucket rate limiter for HTTP requests."""

    def __init__(self, requests_per_second: float = 2.0):
        self.rps = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request_time = time.monotonic()

    def acquire_sync(self) -> None:
        """Synchronous version of acquire."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.monotonic()


class CrawlerHttpClient:
    """
    Production HTTP client with:
    - Automatic retry with exponential backoff
    - Rate limiting
    - Proxy rotation
    - User-Agent rotation
    """

    def __init__(
        self,
        rate_limit_rps: float | None = None,
        timeout: int | None = None,
        proxy_enabled: bool | None = None,
    ):
        settings = get_settings()
        self.rate_limiter = RateLimiter(rate_limit_rps or settings.default_rate_limit_rps)
        self.timeout = timeout or settings.default_timeout_seconds
        self._ua_index = 0

        # Proxy setup
        use_proxy = proxy_enabled if proxy_enabled is not None else settings.proxy_enabled
        self.proxy_rotator: Optional[ProxyRotator] = None
        if use_proxy:
            try:
                self.proxy_rotator = ProxyRotator()
            except Exception as e:
                logger.warning(f"Proxy rotation disabled: {e}")

    def _get_user_agent(self) -> str:
        """Rotate User-Agent strings."""
        ua = USER_AGENTS[self._ua_index % len(USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _get_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Build request headers with rotated User-Agent."""
        headers = {
            "User-Agent": self._get_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json_data: Any = None,
        follow_redirects: bool = True,
    ) -> httpx.Response:
        """
        Fetch a URL with retry, rate limiting, and proxy rotation.

        Raises:
            httpx.HTTPStatusError: For 4xx/5xx responses after retries.
            httpx.TimeoutException: If request times out after retries.
        """
        await self.rate_limiter.acquire()

        proxy = None
        if self.proxy_rotator:
            proxy = self.proxy_rotator.get_next()

        req_headers = self._get_headers(headers)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            proxy=proxy,
            follow_redirects=follow_redirects,
        ) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=req_headers,
                params=params,
                data=data,
                json=json_data,
            )

            # Retry on rate limit (429)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                logger.warning(f"Rate limited (429) on {url}, waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                response.raise_for_status()

            # Raise for other errors
            response.raise_for_status()

            logger.debug(f"Fetched {url} → {response.status_code} ({len(response.content)} bytes)")
            return response

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def fetch_sync(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Synchronous fetch with retry and rate limiting."""
        self.rate_limiter.acquire_sync()

        proxy = None
        if self.proxy_rotator:
            proxy = self.proxy_rotator.get_next()

        req_headers = self._get_headers(headers)

        with httpx.Client(
            timeout=self.timeout,
            proxy=proxy,
            follow_redirects=True,
        ) as client:
            response = client.request(
                method=method,
                url=url,
                headers=req_headers,
                params=params,
            )
            response.raise_for_status()
            return response
