"""Persistent memory subsystem for the crawler agent."""


import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from shared.utils.config import Settings
from shared.utils.logger import get_logger
from src.memory.embeddings import embed_text

logger = get_logger(__name__)


class MemoryManager:
    """Unified Redis + ChromaDB memory API used by the graph."""

    def __init__(self, settings: Settings, redis_client: Any = None):
        self._settings = settings
        self._redis = redis_client
        self._fallback: dict[str, Any] = {}
        self._vector_kb = VectorKnowledgeBase(settings)

    @staticmethod
    def _domain_key(domain: str) -> str:
        return f"agent:domain:{domain}"

    @staticmethod
    def _errors_key(domain: str) -> str:
        return f"agent:errors:{domain}"

    @staticmethod
    def _feedback_key(domain: str) -> str:
        return f"agent:feedback:{domain}"

    @staticmethod
    def _conversation_key(session_id: str) -> str:
        return f"agent:conversation:{session_id}"

    async def _get_json(self, key: str, default: Any) -> Any:
        if self._redis is None:
            return self._fallback.get(key, default)
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else default

    async def _set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self._redis is None:
            self._fallback[key] = value
            return
        await self._redis.set(key, json.dumps(value, default=str), ex=ttl_seconds)

    async def _get_list(self, key: str) -> list[dict[str, Any]]:
        if self._redis is None:
            return list(self._fallback.get(key, []))
        values = await self._redis.lrange(key, 0, -1)
        return [json.loads(value) for value in values]

    async def _append_list(self, key: str, value: dict[str, Any], *, limit: int, ttl_seconds: int) -> None:
        if self._redis is None:
            entries = self._fallback.setdefault(key, [])
            entries.append(value)
            self._fallback[key] = entries[-limit:]
            return
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(key, json.dumps(value, default=str))
            pipe.ltrim(key, -limit, -1)
            pipe.expire(key, ttl_seconds)
            await pipe.execute()

    async def get_domain_context(self, domain: str) -> dict[str, Any]:
        return await self._get_json(self._domain_key(domain), {})

    async def save_domain_context(self, domain: str, context: dict[str, Any]) -> None:
        context = {**context, "_saved_at": datetime.now(UTC).isoformat()}
        await self._set_json(
            self._domain_key(domain),
            context,
            self._settings.domain_memory_ttl_days * 86400,
        )

    async def save_success(
        self,
        domain: str,
        crawler_code: str,
        analysis: dict[str, Any] | None = None,
        artifact_path: str | None = None,
    ) -> None:
        context = {
            "crawler_code": crawler_code[:5000],
            "artifact_path": artifact_path,
            "analysis": analysis,
            "status": "success",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await self.save_domain_context(domain, context)
        await self._vector_kb.index(
            domain=domain,
            data_type=(analysis or {}).get("data_type", "unknown"),
            strategy=context,
        )

    async def get_known_errors(self, domain: str) -> list[dict[str, Any]]:
        return await self._get_list(self._errors_key(domain))

    async def save_error(
        self,
        domain: str,
        error: str,
        error_type: str = "unknown",
        context: dict[str, Any] | None = None,
    ) -> None:
        await self._append_list(
            self._errors_key(domain),
            {
                "error": error,
                "error_type": error_type,
                "context": context or {},
                "timestamp": datetime.now(UTC).isoformat(),
            },
            limit=20,
            ttl_seconds=self._settings.error_memory_ttl_days * 86400,
        )

    async def get_conversation_history(self, session_id: str) -> list[dict[str, Any]]:
        return await self._get_list(self._conversation_key(session_id))

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        await self._append_list(
            self._conversation_key(session_id),
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            limit=self._settings.conversation_buffer_size,
            ttl_seconds=self._settings.domain_memory_ttl_days * 86400,
        )

    async def clear_conversation(self, session_id: str) -> None:
        key = self._conversation_key(session_id)
        if self._redis is None:
            self._fallback.pop(key, None)
        else:
            await self._redis.delete(key)

    async def get_similar_sites(self, domain: str, data_type: str = "") -> list[dict[str, Any]]:
        return await self._vector_kb.query(domain, data_type)

    async def get_human_feedback(self, domain: str) -> list[dict[str, Any]]:
        return await self._get_list(self._feedback_key(domain))

    async def save_human_feedback(
        self,
        domain: str,
        feedback: str,
        feedback_type: str = "correction",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._append_list(
            self._feedback_key(domain),
            {
                "feedback": feedback,
                "type": feedback_type,
                "metadata": metadata or {},
                "timestamp": datetime.now(UTC).isoformat(),
            },
            limit=50,
            ttl_seconds=self._settings.human_feedback_ttl_days * 86400,
        )

    async def healthcheck(self) -> dict[str, Any]:
        redis_ok = self._redis is not None
        if self._redis is not None:
            try:
                redis_ok = bool(await self._redis.ping())
            except Exception:
                redis_ok = False
        return {"redis": redis_ok, "vector_store": self._vector_kb.available}


class VectorKnowledgeBase:
    """ChromaDB-backed strategy similarity index."""

    def __init__(self, settings: Settings):
        self._collection = None
        try:
            import chromadb

            client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            self._collection = client.get_or_create_collection(
                name="crawl_knowledge_base",
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
        except Exception:
            logger.warning("ChromaDB unavailable for VectorKB", exc_info=True)

    @property
    def available(self) -> bool:
        return self._collection is not None

    async def index(self, domain: str, data_type: str, strategy: dict[str, Any]) -> None:
        if self._collection is None:
            return
        document = json.dumps(
            {
                "domain": domain,
                "data_type": data_type,
                "strategy": strategy,
                "indexed_at": datetime.now(UTC).isoformat(),
            },
            default=str,
        )
        try:
            await asyncio.to_thread(
                self._collection.upsert,
                ids=[f"{domain}:{data_type}"],
                documents=[document],
                metadatas=[{"domain": domain, "data_type": data_type}],
                embeddings=[embed_text(document)],
            )
        except Exception:
            logger.warning("Failed to index strategy for %s", domain, exc_info=True)

    async def query(self, domain: str, data_type: str = "", n_results: int = 3) -> list[dict[str, Any]]:
        if self._collection is None:
            return []
        try:
            count = await asyncio.to_thread(self._collection.count)
            if not count:
                return []
            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[embed_text(f"{domain} {data_type}")],
                n_results=min(n_results, count),
                where={"domain": {"$ne": domain}},
            )
            documents = (results.get("documents") or [[]])[0]
            return [json.loads(document) for document in documents]
        except Exception:
            logger.warning("Failed to query similar strategies for %s", domain, exc_info=True)
            return []
