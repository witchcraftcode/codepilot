"""Redis cache service for embeddings, agent memory, and sessions."""

import json
from typing import Any

import redis.asyncio as redis

from app.config import get_settings


class CacheService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._settings.redis_url, decode_responses=True)
        await self._client.ping()

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()

    @property
    def client(self) -> redis.Redis:
        if not self._client:
            raise RuntimeError("Cache not connected")
        return self._client

    async def get(self, key: str) -> Any | None:
        data = await self.client.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl or self._settings.cache_ttl_seconds
        await self.client.setex(key, ttl, json.dumps(value))

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def get_embedding_cache(self, content_hash: str) -> list[float] | None:
        return await self.get(f"emb:{content_hash}")

    async def set_embedding_cache(self, content_hash: str, embedding: list[float]) -> None:
        await self.set(f"emb:{content_hash}", embedding, ttl=86400 * 7)

    async def get_agent_memory(self, review_id: str, agent_name: str) -> dict | None:
        return await self.get(f"agent_mem:{review_id}:{agent_name}")

    async def set_agent_memory(self, review_id: str, agent_name: str, memory: dict) -> None:
        await self.set(f"agent_mem:{review_id}:{agent_name}", memory, ttl=3600)


cache_service = CacheService()
