"""Outbound network policy for crawler targets.

The crawler accepts user-controlled URLs, so every outbound target must resolve
only to globally routable IP addresses. Validation must be repeated after every
redirect because a public URL may redirect to an internal service.
"""

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx


class UnsafeTargetError(ValueError):
    """Raised when a URL could reach a non-public network destination."""


def validate_http_url_syntax(url: str) -> str:
    """Validate URL syntax and reject obvious private/internal targets without DNS."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeTargetError("Only http and https targets are allowed")
    if not parsed.hostname:
        raise UnsafeTargetError("Target URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("Credentials embedded in target URLs are not allowed")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError("Target URL contains an invalid port") from exc

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise UnsafeTargetError(
            f"Non-public target hostname is not allowed: {hostname}"
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", hostname):
            raise UnsafeTargetError(
                "Target hostname contains unsupported characters"
            ) from None
        labels = hostname.split(".")
        if any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in labels
        ):
            raise UnsafeTargetError("Target hostname is malformed") from None
        return url
    if not address.is_global:
        raise UnsafeTargetError(f"Non-public target address is not allowed: {address}")
    return url


def validate_public_http_url(url: str) -> str:
    """Validate that an HTTP(S) URL resolves exclusively to public IPs."""
    resolve_public_http_url(url)
    return url


def resolve_public_http_url(url: str) -> list[str]:
    """Resolve a URL to a stable list containing only globally routable IPs."""
    validate_http_url_syntax(url)
    parsed = urlparse(url)
    hostname = parsed.hostname.rstrip(".").lower()

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(
                hostname, parsed.port, type=socket.SOCK_STREAM
            )
        }
    except socket.gaierror as exc:
        raise UnsafeTargetError(
            f"Target hostname could not be resolved: {hostname}"
        ) from exc

    if not addresses:
        raise UnsafeTargetError(f"Target hostname did not resolve: {hostname}")

    normalized: list[str] = []
    for address in sorted(
        addresses, key=lambda value: (ipaddress.ip_address(value).version, value)
    ):
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeTargetError(f"Non-public target address is not allowed: {ip}")
        normalized.append(str(ip))
    return normalized


async def validate_public_http_url_async(url: str) -> str:
    """Async wrapper around public URL validation."""
    return await asyncio.to_thread(validate_public_http_url, url)


async def resolve_public_http_url_async(url: str) -> list[str]:
    """Async wrapper around public URL resolution."""
    return await asyncio.to_thread(resolve_public_http_url, url)


def _pinned_request_target(url: str, address: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    ip = ipaddress.ip_address(address)
    pinned_host = f"[{ip}]" if ip.version == 6 else str(ip)
    if parsed.port:
        pinned_host = f"{pinned_host}:{parsed.port}"
    pinned_url = urlunparse(parsed._replace(netloc=pinned_host))
    host_header = hostname
    if parsed.port:
        host_header = f"{host_header}:{parsed.port}"
    return pinned_url, host_header, hostname


def _request_options(
    kwargs: dict[str, Any], host_header: str, hostname: str
) -> dict[str, Any]:
    options = dict(kwargs)
    options.pop("follow_redirects", None)
    headers = httpx.Headers(options.pop("headers", None))
    headers["Host"] = host_header
    extensions = dict(options.pop("extensions", None) or {})
    extensions["sni_hostname"] = hostname
    return {**options, "headers": headers, "extensions": extensions}


async def safe_async_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_redirects: int = 5,
    **kwargs: Any,
) -> httpx.Response:
    """Send a DNS-rebinding-safe request and validate every redirect."""
    current_url = url
    for _ in range(max_redirects + 1):
        addresses = await resolve_public_http_url_async(current_url)
        response: httpx.Response | None = None
        last_error: httpx.TransportError | None = None
        for address in addresses:
            pinned_url, host_header, hostname = _pinned_request_target(
                current_url, address
            )
            try:
                response = await client.request(
                    method,
                    pinned_url,
                    follow_redirects=False,
                    **_request_options(kwargs, host_header, hostname),
                )
                break
            except httpx.TransportError as exc:
                last_error = exc
        if response is None:
            raise last_error or UnsafeTargetError(
                f"No public target was reachable for {current_url}"
            )
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current_url = urljoin(current_url, location)
    raise UnsafeTargetError(f"Too many redirects while requesting {url}")


def safe_sync_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_redirects: int = 5,
    **kwargs: Any,
) -> httpx.Response:
    """Synchronous variant of :func:`safe_async_request`."""
    current_url = url
    for _ in range(max_redirects + 1):
        addresses = resolve_public_http_url(current_url)
        response: httpx.Response | None = None
        last_error: httpx.TransportError | None = None
        for address in addresses:
            pinned_url, host_header, hostname = _pinned_request_target(
                current_url, address
            )
            try:
                response = client.request(
                    method,
                    pinned_url,
                    follow_redirects=False,
                    **_request_options(kwargs, host_header, hostname),
                )
                break
            except httpx.TransportError as exc:
                last_error = exc
        if response is None:
            raise last_error or UnsafeTargetError(
                f"No public target was reachable for {current_url}"
            )
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current_url = urljoin(current_url, location)
    raise UnsafeTargetError(f"Too many redirects while requesting {url}")


async def guard_playwright_route(
    route: Any, allowed_hosts: set[str] | None = None
) -> None:
    """Abort Playwright requests that could reach private/internal networks."""
    request_url = route.request.url
    hostname = (urlparse(request_url).hostname or "").lower()
    try:
        if allowed_hosts is not None and hostname not in allowed_hosts:
            raise UnsafeTargetError(
                f"Host is outside the allowed crawl scope: {hostname}"
            )
        await validate_public_http_url_async(request_url)
    except UnsafeTargetError:
        await route.abort("blockedbyclient")
        return
    await route.continue_()
