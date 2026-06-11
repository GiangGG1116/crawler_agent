"""Lifecycle-managed durable LangGraph checkpointers."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from shared.utils.config import Settings
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class CheckpointManager:
    """Own the selected checkpointer and its connection lifecycle."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._stack = AsyncExitStack()
        self.saver: Any = None
        self.backend = "uninitialized"
        self.durable = False

    async def start(self) -> Any:
        backend = self._settings.checkpoint_backend.lower()
        try:
            if backend == "redis":
                from langgraph.checkpoint.redis.aio import AsyncRedisSaver

                context = AsyncRedisSaver.from_conn_string(self._settings.redis_url)
                self.saver = await self._stack.enter_async_context(context)
                await self.saver.setup()
                self.backend = "redis"
                self.durable = True
            elif backend == "sqlite":
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                path = self._settings.generated_crawlers_dir / "checkpoints.db"
                context = AsyncSqliteSaver.from_conn_string(str(path))
                self.saver = await self._stack.enter_async_context(context)
                await self.saver.setup()
                self.backend = "sqlite"
                self.durable = True
            else:
                raise ValueError(f"Unsupported checkpoint backend: {backend}")
        except Exception:
            if self._settings.app_env.lower() == "production":
                raise
            from langgraph.checkpoint.memory import InMemorySaver

            logger.warning(
                "Durable checkpointer unavailable; using development in-memory fallback",
                exc_info=True,
            )
            self.saver = InMemorySaver()
            self.backend = "memory"
            self.durable = False
        return self.saver

    async def close(self) -> None:
        await self._stack.aclose()
