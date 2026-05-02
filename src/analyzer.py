"""Phase 0 — Input Analysis & Web Type Classification.

Analyzes target URLs to determine the best crawling strategy by classifying
websites into: STATIC, DYNAMIC, API_BASED, PAGINATED, AUTHENTICATED.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from src.models.request import CrawlRequest, WebType
from src.utils.http_client import CrawlerHttpClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Detection signal patterns
# ─────────────────────────────────────────────────────────────────────────────

JS_FRAMEWORK_PATTERNS = [
    r"__NEXT_DATA__",
    r"__NUXT__",
    r"window\.__STATE__",
    r"window\.__INITIAL_STATE__",
    r'id="__next"',
    r'id="app"',
    r'id="root"',
    r"react",
    r"vue",
    r"angular",
    r"svelte",
    r"ember",
]

API_ENDPOINT_PATTERNS = [
    r"/api/v\d+",
    r"/api/",
    r"/graphql",
    r"/rest/",
    r"application/json",
]

PAGINATION_PATTERNS = [
    r"\?page=\d+",
    r"&page=\d+",
    r"\?offset=\d+",
    r"&offset=\d+",
    r"\?p=\d+",
    r"/page/\d+",
]

AUTH_PATTERNS = [
    r'type=["\']password["\']',
    r"login",
    r"signin",
    r"sign-in",
    r"authenticate",
]

PAGINATION_LINK_SELECTORS = [
    "a.next",
    "a.next-page",
    'a[rel="next"]',
    ".pagination a",
    "nav.pagination",
    ".pager a",
    'button[aria-label="Next"]',
]


class WebAnalyzer:
    """
    Analyzes a target URL to classify website type and gather metadata.

    Detection order (from implementation plan):
    1. Has public API? → API_BASED
    2. JS-rendered content? → DYNAMIC
    3. Requires login? → AUTHENTICATED
    4. Multi-page listing? → PAGINATED
    5. Otherwise → STATIC
    """

    def __init__(self, http_client: CrawlerHttpClient | None = None):
        self.http_client = http_client or CrawlerHttpClient(proxy_enabled=False)

    async def analyze(self, request: CrawlRequest) -> AnalysisResult:
        """
        Run full analysis on the target URL.

        Returns an AnalysisResult with detected web_type and metadata.
        Also updates the request's target.web_type in place.
        """
        url = request.target.url
        logger.info(f"Analyzing URL: {url}", extra={"request_id": request.request_id, "phase": "phase0"})

        result = AnalysisResult(url=url, domain=request.extract_domain())

        try:
            response = await self.http_client.fetch(url)
            page_source = response.text
            headers = dict(response.headers)
            status_code = response.status_code
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                result.web_type = WebType.AUTHENTICATED
                result.signals.append(f"HTTP {e.response.status_code} — requires authentication")
                request.target.web_type = result.web_type
                return result
            raise
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            result.web_type = WebType.STATIC  # Default fallback
            result.signals.append(f"Fetch error, defaulting to STATIC: {e}")
            request.target.web_type = result.web_type
            return result

        # ─── Detection pipeline ─────────────────────────────────────────

        # 1. Check for API endpoints
        if self._detect_api(page_source, headers, url):
            result.web_type = WebType.API_BASED
            result.signals.append("API endpoints detected")

        # 2. Check for JS frameworks / dynamic rendering
        elif self._detect_dynamic(page_source):
            result.web_type = WebType.DYNAMIC
            result.signals.append("JavaScript framework / SPA detected")

        # 3. Check for authentication requirements
        elif self._detect_auth(page_source, status_code):
            result.web_type = WebType.AUTHENTICATED
            result.signals.append("Authentication required (login form detected)")

        # 4. Check for pagination
        elif self._detect_pagination(page_source, url):
            result.web_type = WebType.PAGINATED
            result.signals.append("Pagination pattern detected")

        # 5. Default: Static
        else:
            result.web_type = WebType.STATIC
            result.signals.append("Plain HTML, no dynamic patterns detected")

        # Update request in place
        request.target.web_type = result.web_type
        request.target.domain = result.domain

        logger.info(
            f"Classification: {result.web_type.value}",
            extra={"request_id": request.request_id, "phase": "phase0"},
        )
        return result

    def _detect_api(self, page_source: str, headers: dict, url: str) -> bool:
        """Check for API-based website signals."""
        # Content-Type is JSON
        content_type = headers.get("content-type", "")
        if "application/json" in content_type:
            return True
        # URL contains API patterns
        for pattern in API_ENDPOINT_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return True
            if re.search(pattern, page_source, re.IGNORECASE):
                return True
        return False

    def _detect_dynamic(self, page_source: str) -> bool:
        """Check for JavaScript-rendered content signals."""
        matches = 0
        for pattern in JS_FRAMEWORK_PATTERNS:
            if re.search(pattern, page_source, re.IGNORECASE):
                matches += 1
        # Require at least 2 signals to avoid false positives
        return matches >= 2

    def _detect_auth(self, page_source: str, status_code: int) -> bool:
        """Check for authentication requirements."""
        if status_code in (401, 403):
            return True
        auth_signals = 0
        for pattern in AUTH_PATTERNS:
            if re.search(pattern, page_source, re.IGNORECASE):
                auth_signals += 1
        # Login form typically has password input + login-related keywords
        has_password_field = bool(re.search(r'type=["\']password["\']', page_source, re.IGNORECASE))
        return has_password_field and auth_signals >= 2

    def _detect_pagination(self, page_source: str, url: str) -> bool:
        """Check for pagination patterns."""
        # URL patterns
        for pattern in PAGINATION_PATTERNS:
            if re.search(pattern, url):
                return True
            if re.search(pattern, page_source):
                return True
        # DOM patterns
        for selector_hint in PAGINATION_LINK_SELECTORS:
            # Simple check: look for the class/rel/tag in source
            clean = selector_hint.replace("a.", "").replace(".", " ").replace('a[rel="next"]', 'rel="next"')
            if clean in page_source:
                return True
        return False


class AnalysisResult:
    """Result of Phase 0 URL analysis."""

    def __init__(self, url: str, domain: str = ""):
        self.url = url
        self.domain = domain
        self.web_type: Optional[WebType] = None
        self.signals: list[str] = []
        self.metadata: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "web_type": self.web_type.value if self.web_type else None,
            "signals": self.signals,
            "metadata": self.metadata,
        }
