"""API Key authentication — lightweight auth middleware for production.

Usage in routers::

    from shared.utils.security import require_api_key
    from fastapi import Depends

    @router.post("/crawl", dependencies=[Depends(require_api_key)])
    async def submit_crawl_job(...):
        ...

When ``API_KEY`` is empty or unset, authentication is **skipped** (dev mode).
In production, set ``API_KEY`` in ``.env`` to enforce authentication.
"""

import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from shared.utils.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_internal_token_header = APIKeyHeader(name="X-Internal-Service-Token", auto_error=False)


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """Validate the ``X-API-Key`` header against the configured key.

    - If ``API_KEY`` is not configured → skip auth (dev mode).
    - If ``API_KEY`` is configured and header matches → allow.
    - Otherwise → 401 Unauthorized.

    Returns:
        The validated API key, or ``None`` in dev mode.
    """
    settings = get_settings()

    # Dev mode: no key configured → allow all requests
    if not settings.api_key:
        return None

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "authentication_error",
                "message": "Missing API key. Provide X-API-Key header.",
            },
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_error", "message": "Invalid API key."},
        )

    return api_key


async def require_internal_service_token(
    token: str | None = Security(_internal_token_header),
) -> str | None:
    """Authenticate calls between internal microservices."""
    settings = get_settings()
    if not settings.internal_service_token:
        if settings.app_env.lower() == "production":
            raise HTTPException(
                status_code=503,
                detail="Internal service authentication is not configured",
            )
        return None
    if not token or not secrets.compare_digest(token, settings.internal_service_token):
        raise HTTPException(status_code=401, detail="Invalid internal service token")
    return token
