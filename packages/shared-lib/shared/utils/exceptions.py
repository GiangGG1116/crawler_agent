"""Custom exceptions — structured error handling for production.

Replaces generic ``except Exception`` with typed exceptions that map
to proper HTTP status codes.  Register handlers on the FastAPI app
with ``register_exception_handlers(app)`` in each service's ``main.py``.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from shared.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Exception Classes
# =============================================================================


class CrawlerBaseError(Exception):
    """Base exception for all crawler platform errors."""

    status_code: int = 500
    error_type: str = "internal_error"

    def __init__(
        self, message: str = "An internal error occurred", details: Any = None
    ):
        self.message = message
        self.details = details
        super().__init__(self.message)


class CrawlValidationError(CrawlerBaseError):
    """Invalid input from the client (bad URL, missing fields, etc.)."""

    status_code = 400
    error_type = "validation_error"


class CrawlAuthenticationError(CrawlerBaseError):
    """Missing or invalid API key."""

    status_code = 401
    error_type = "authentication_error"

    def __init__(self, message: str = "Invalid or missing API key"):
        super().__init__(message)


class ServiceUnavailableError(CrawlerBaseError):
    """A downstream microservice is unreachable."""

    status_code = 503
    error_type = "service_unavailable"


class CrawlJobError(CrawlerBaseError):
    """An internal processing error within the crawl pipeline."""

    status_code = 500
    error_type = "crawl_job_error"


class CrawlTimeoutError(CrawlerBaseError):
    """A crawl operation exceeded its time limit."""

    status_code = 504
    error_type = "timeout_error"


# =============================================================================
# FastAPI Exception Handlers
# =============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """Mount global exception handlers on a FastAPI application.

    Call this once in every service's ``main.py`` after creating the app::

        app = FastAPI(...)
        register_exception_handlers(app)
    """

    @app.exception_handler(CrawlerBaseError)
    async def _crawler_error_handler(
        request: Request, exc: CrawlerBaseError
    ) -> JSONResponse:
        logger.error(
            "Request failed: %s — %s",
            exc.error_type,
            exc.message,
            extra={"error_type": exc.error_type},
        )
        body: dict[str, Any] = {
            "error": exc.error_type,
            "message": exc.message,
        }
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Never leak internal stack traces to the client
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again later.",
            },
        )
