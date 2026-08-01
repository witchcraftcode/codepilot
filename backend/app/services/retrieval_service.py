"""Semantic retrieval service using Qdrant vector store."""

import time
from typing import Any, List
from uuid import UUID

from app.services.observability import record_retrieval, trace_span
from vectorstore.qdrant_store import VectorStore


class RetrievalService:
    def __init__(self) -> None:
        self.vector_store = VectorStore()

    async def retrieve(self, repository_id: UUID, query: str, k: int = 5, chunk_types: List[str] | None = None, language: str | None = None) -> dict[str, Any]:
        start = time.perf_counter()
        with trace_span("retrieval.semantic", repository_id=str(repository_id), limit=k):
            results = await self.vector_store.search(query=query, repository_id=str(repository_id), limit=k, chunk_types=chunk_types, language=language)
        end = time.perf_counter()
        latency_ms = int((end - start) * 1000)
        record_retrieval("semantic", latency_ms)
        return {"retrieved": results, "latency_ms": latency_ms}
