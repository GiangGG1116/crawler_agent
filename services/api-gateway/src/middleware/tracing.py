"""Request tracing middleware — propagates correlation IDs across services.

Adds ``X-Request-ID`` header to every request/response. If the client
provides one, it is reused; otherwise a new UUID is generated.

This enables distributed tracing: every log line, inter-service call,
and error report carries the same correlation ID.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Async-safe storage for the current request ID
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

HEADER_NAME = "X-Request-ID"


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Inject and propagate X-Request-ID on every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Reuse client-provided ID or generate a new one
        req_id = request.headers.get(HEADER_NAME) or str(uuid.uuid4())
        request_id_ctx.set(req_id)

        # Make it available via request.state for downstream code
        request.state.request_id = req_id

        response = await call_next(request)
        response.headers[HEADER_NAME] = req_id
        return response
