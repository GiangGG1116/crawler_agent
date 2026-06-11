"""Shared robots.txt preflight used before any target-page request."""

from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from shared.utils.network import safe_async_request

DEFAULT_CRAWLER_USER_AGENT = "QualifyCrawler"


async def check_robots(
    url: str, user_agent: str = DEFAULT_CRAWLER_USER_AGENT
) -> dict[str, Any]:
    """Return robots.txt evidence without requesting the target page."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = urljoin(f"{origin}/", "robots.txt")
    result: dict[str, Any] = {
        "url": robots_url,
        "status": "unavailable",
        "http_status": None,
        "allowed": None,
        "reason": "robots.txt is unavailable; crawl permission could not be determined",
    }

    try:
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await safe_async_request(client, "GET", robots_url)
    except (httpx.HTTPError, ValueError) as exc:
        result["reason"] = f"robots.txt could not be fetched: {type(exc).__name__}"
        return result

    result["http_status"] = response.status_code
    if response.status_code == 404:
        result.update(
            {
                "status": "not_found",
                "allowed": True,
                "reason": "robots.txt was not found",
            }
        )
        return result
    if response.status_code >= 400:
        result["reason"] = f"robots.txt returned HTTP {response.status_code}"
        return result

    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    allowed = parser.can_fetch(user_agent, url)
    result.update(
        {
            "status": "available",
            "allowed": allowed,
            "reason": (
                "robots.txt allows this URL"
                if allowed
                else "robots.txt disallows this URL"
            ),
        }
    )
    return result
