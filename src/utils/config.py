"""Application configuration — centralized settings management.

Loads from .env file with pydantic-settings for validation and type safety.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ProxyStrategy(str, Enum):
    """Proxy rotation strategies."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


class LogFormat(str, Enum):
    """Log output format."""
    JSON = "json"
    TEXT = "text"


# Derive project root from this file's location: src/utils/config.py → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM Providers ---
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_llm_provider: LLMProvider = LLMProvider.ANTHROPIC

    # --- MinIO (Data Lake) ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_raw: str = "crawler-raw"
    minio_bucket_clean: str = "crawler-clean"
    minio_bucket_audit: str = "crawler-audit"
    minio_bucket_generated: str = "crawler-generated"
    minio_use_ssl: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Celery ---
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Proxy Rotation ---
    proxy_enabled: bool = True
    proxy_list_path: str = "configs/proxies.txt"
    proxy_rotation_strategy: ProxyStrategy = ProxyStrategy.ROUND_ROBIN

    # --- Crawling Defaults ---
    default_rate_limit_rps: float = 2.0
    default_max_pages: int = 100
    default_max_records: int = 10000
    default_timeout_seconds: int = 30
    respect_robots_txt: bool = True

    # --- Logging ---
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.TEXT

    # --- Agent ---
    agent_max_retries: int = 3
    agent_code_execution_timeout: int = 120

    # --- Derived Paths ---
    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def generated_crawlers_dir(self) -> Path:
        path = PROJECT_ROOT / "generated_crawlers"
        path.mkdir(exist_ok=True)
        return path

    @property
    def configs_dir(self) -> Path:
        return PROJECT_ROOT / "configs"

    @property
    def templates_config_dir(self) -> Path:
        return PROJECT_ROOT / "configs" / "templates"

    @property
    def logs_dir(self) -> Path:
        path = PROJECT_ROOT / "logs"
        path.mkdir(exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
