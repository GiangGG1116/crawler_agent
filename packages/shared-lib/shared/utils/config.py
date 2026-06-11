"""Application configuration — centralized settings management.

Loads from .env file with pydantic-settings for validation and type safety.
"""

import logging
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ProxyStrategy(StrEnum):
    """Proxy rotation strategies."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


class LogFormat(StrEnum):
    """Log output format."""

    JSON = "json"
    TEXT = "text"


# Derived from the location of this config file within a service:
# e.g. services/api-gateway/src/... -> service root is 2 levels up from shared install
# We use env var SERVICE_ROOT to let each service override its own root path.


def _find_env_file() -> Path:
    # 1. Respect SERVICE_ROOT if set
    service_root = os.environ.get("SERVICE_ROOT")
    if service_root:
        return Path(service_root) / ".env"

    # 2. Look for .env walking up from current working directory
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd] + list(cwd.parents):
        p = parent / ".env"
        if p.exists():
            return p

    # 3. Fallback to package location
    fallback_root = Path(__file__).resolve().parent.parent.parent
    return fallback_root / ".env"


_ENV_FILE = _find_env_file()
_DEFAULT_ROOT = _ENV_FILE.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API Security ---
    app_env: str = "development"
    api_key: str = ""  # Empty = dev mode (no auth). Set in production.
    internal_service_token: str = ""
    allowed_origins: str = ""  # Comma-separated. Empty = allow all (dev).

    # --- Service URLs (used by api-gateway to call other services) ---
    crawler_service_url: str = "http://crawler-service:8001"
    agent_service_url: str = "http://agent-service:8002"
    processor_service_url: str = "http://data-processor:8003"

    # --- LLM Providers ---
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    llm_max_tokens: int = 4096

    # --- MinIO (Data Lake) ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_raw: str = "crawler-raw"
    minio_bucket_clean: str = "crawler-clean"
    minio_bucket_audit: str = "crawler-audit"
    minio_bucket_generated: str = "crawler-generated"
    minio_use_ssl: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Durable Job Queue ---
    job_queue_key: str = "crawl_jobs:queued"
    job_processing_queue_key: str = "crawl_jobs:processing"
    job_dead_letter_queue_key: str = "crawl_jobs:dead_letter"
    job_worker_poll_timeout_seconds: int = 5

    # --- Approved network proxy routing (never use to bypass access controls) ---
    proxy_enabled: bool = False
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
    agent_sandbox_backend: str = "bubblewrap"
    agent_sandbox_memory_mb: int = 512
    agent_sandbox_cpu_seconds: int = 120
    agent_sandbox_max_processes: int = 64
    agent_min_field_completeness: float = 0.8
    agent_generated_artifact_ttl_hours: int = 24
    agent_alert_webhook_url: str = ""
    checkpoint_backend: str = "sqlite"  # "sqlite" | "redis"

    # --- Agent Memory ---
    domain_memory_ttl_days: int = 7
    error_memory_ttl_days: int = 14
    human_feedback_ttl_days: int = 30
    conversation_buffer_size: int = 10
    chroma_persist_dir: str = "chroma_data"

    # --- Langfuse Observability ---
    langfuse_enabled: bool = True
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # --- Derived Paths ---
    @property
    def project_root(self) -> Path:
        return _DEFAULT_ROOT

    @property
    def generated_crawlers_dir(self) -> Path:
        path = _DEFAULT_ROOT / "generated_crawlers"
        path.mkdir(exist_ok=True)
        return path

    @property
    def configs_dir(self) -> Path:
        return _DEFAULT_ROOT / "configs"

    @property
    def templates_config_dir(self) -> Path:
        return _DEFAULT_ROOT / "configs" / "templates"

    @property
    def logs_dir(self) -> Path:
        path = _DEFAULT_ROOT / "logs"
        path.mkdir(exist_ok=True)
        return path

    def validate_production(
        self,
        *,
        require_api_auth: bool = False,
        require_internal_auth: bool = True,
        require_minio: bool = False,
        require_sandbox: bool = False,
    ) -> None:
        """Fail startup when role-specific production security settings are absent."""
        if self.app_env.lower() != "production":
            return
        required: dict[str, str] = {}
        if require_api_auth:
            required.update(
                {"API_KEY": self.api_key, "ALLOWED_ORIGINS": self.allowed_origins}
            )
        if require_internal_auth:
            required["INTERNAL_SERVICE_TOKEN"] = self.internal_service_token
        if require_minio:
            required.update(
                {
                    "MINIO_ACCESS_KEY": self.minio_access_key,
                    "MINIO_SECRET_KEY": self.minio_secret_key,
                }
            )
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing required production settings: {', '.join(missing)}"
            )
        if require_sandbox and self.agent_sandbox_backend != "bubblewrap":
            raise RuntimeError("AGENT_SANDBOX_BACKEND must be bubblewrap in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    settings = Settings()

    if settings.langfuse_enabled and settings.langfuse_public_key:
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host

        try:
            from langfuse import Langfuse

            # Pre-initialize Langfuse client to register it globally
            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            # Suppress OpenTelemetry span export warnings/errors (e.g. 404 OTLP on v2 server)
            logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
        except Exception:
            logging.getLogger(__name__).debug(
                "Langfuse pre-initialization failed", exc_info=True
            )

    return settings
