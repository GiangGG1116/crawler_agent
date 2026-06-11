"""Configured LLM clients with retry and provider fallback."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from shared.utils.config import LLMProvider, get_settings
from shared.utils.logger import get_logger
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

logger = get_logger(__name__)


@lru_cache(maxsize=2)
def _get_provider_llm(provider: LLMProvider):
    settings = get_settings()
    if provider == LLMProvider.ANTHROPIC:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            anthropic_api_key=settings.anthropic_api_key,
            max_tokens=settings.llm_max_tokens,
            temperature=0,
        )
    if provider == LLMProvider.OPENAI:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            max_tokens=settings.llm_max_tokens,
            temperature=0,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")


def get_llm():
    """Return the configured primary LLM."""
    return _get_provider_llm(get_settings().default_llm_provider)


def _providers() -> list[LLMProvider]:
    settings = get_settings()
    primary = settings.default_llm_provider
    secondary = (
        LLMProvider.OPENAI
        if primary == LLMProvider.ANTHROPIC
        else LLMProvider.ANTHROPIC
    )
    providers = [primary]
    if secondary == LLMProvider.OPENAI and settings.openai_api_key:
        providers.append(secondary)
    if secondary == LLMProvider.ANTHROPIC and settings.anthropic_api_key:
        providers.append(secondary)
    return providers


async def ainvoke_llm(
    messages: list[Any],
    *,
    config: dict[str, Any] | None = None,
    structured_schema: type[Any] | None = None,
) -> Any:
    """Invoke the primary LLM with retries, then fall back to the other provider."""
    errors: list[str] = []
    for provider in _providers():
        try:
            model = _get_provider_llm(provider)
            if structured_schema is not None:
                model = model.with_structured_output(structured_schema)
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                reraise=True,
            ):
                with attempt:
                    return await model.ainvoke(messages, config=config or {})
        except Exception as exc:
            errors.append(f"{provider.value}: {exc}")
            logger.warning(
                "LLM provider %s failed; trying fallback", provider.value, exc_info=True
            )
    raise RuntimeError("All configured LLM providers failed: " + "; ".join(errors))
