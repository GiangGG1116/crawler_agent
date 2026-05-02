"""Structured logging — supports JSON and text format.

Provides per-module loggers with consistent formatting and optional file output.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = self.formatException(record.exc_info)
        # Include extra fields if present
        for key in ("request_id", "phase", "template_id", "url", "attempt"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        return json.dumps(log_data, ensure_ascii=False)


class RichTextFormatter(logging.Formatter):
    """Colored text formatter for development use."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = ""
        for key in ("request_id", "phase"):
            if hasattr(record, key):
                prefix += f"[{getattr(record, key)}] "
        return (
            f"{color}{timestamp} │ {record.levelname:<8}{self.RESET} │ "
            f"{prefix}{record.name} → {record.getMessage()}"
        )


_initialized: set[str] = set()


def get_logger(
    name: str,
    level: str | None = None,
    log_format: str | None = None,
    log_file: Path | None = None,
) -> logging.Logger:
    """
    Get or create a named logger with consistent formatting.

    Args:
        name: Logger name (typically __name__).
        level: Override log level. Defaults to settings.
        log_format: "json" or "text". Defaults to settings.
        log_file: Optional file path for log output.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)

    if name in _initialized:
        return logger

    # Import settings lazily to avoid circular imports
    from src.utils.config import get_settings
    settings = get_settings()

    effective_level = level or settings.log_level
    effective_format = log_format or settings.log_format.value

    logger.setLevel(getattr(logging, effective_level.upper(), logging.INFO))
    logger.propagate = False

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if effective_format == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(RichTextFormatter())
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())  # Always JSON for files
        logger.addHandler(file_handler)

    _initialized.add(name)
    return logger
