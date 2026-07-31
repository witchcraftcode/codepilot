"""Qdrant vector store integration for code chunk retrieval."""

import hashlib
import uuid
from typing import Any

from app.config import get_settings
from app.services.cache import cache_service
from parsers.chunker import CodeChunk


class VectorStore:
    def __init__(self) -> None:
        # Lazy import of qdrant to avoid import-time dependency during unit tests
        try:
            from qdrant_client import QdrantClient
        except Exception:  # pragma: no cover - environment may not have qdrant
            QdrantClient = None  # type: ignore

        self.settings = get_settings()
        self.client = QdrantClient(url=self.settings.qdrant_url) if QdrantClient else None
        # Lazy import of embedding provider to avoid test-time dependency
        try:
            from app.services.embedding_factory import get_embeddings

            self.embeddings = get_embeddings()
        except Exception:
            self.embeddings = None

    def ensure_collection(self) -> None:
        # Lazy import models to avoid test-time dependency
        from qdrant_client.http import models as qmodels

        if not self.client:
            return
        collections = [c.name for c in self.client.get_collections().collections]
        if self.settings.qdrant_collection not in collections:
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(
                    size=self.settings.vector_dimension,
                    distance=qmodels.Distance.COSINE,
                ),
            )

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    async def _get_embedding(self, content: str) -> list[float]:
        content_hash = self._content_hash(content)
        cached = await cache_service.get_embedding_cache(content_hash)
        if cached:
            return cached
        if not self.embeddings:
            # No embeddings provider configured in test environment
            return [0.0] * self.settings.vector_dimension
        embedding = await self.embeddings.aembed_query(content)
        await cache_service.set_embedding_cache(content_hash, embedding)
        return embedding

    async def index_chunks(self, repository_id: str, chunks: list[CodeChunk]) -> int:
        self.ensure_collection()
        from qdrant_client.http import models as qmodels
        points: list[qmodels.PointStruct] = []
        indexed = 0

        for chunk in chunks:
            if len(chunk.content.strip()) < 10:
                continue
            embedding = await self._get_embedding(chunk.content)
            point_id = str(uuid.uuid4())
            payload = {
                "repository_id": repository_id,
                "file_path": chunk.file_path,
                "language": chunk.language,
                "symbol_name": chunk.symbol_name,
                "symbol_type": chunk.chunk_type,
                "chunk_type": chunk.chunk_type,
                "parent_symbol": chunk.parent_symbol,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content[:2000],
                "content_hash": self._content_hash(chunk.content),
            }
            points.append(
                qmodels.PointStruct(id=point_id, vector=embedding, payload=payload)
            )
            indexed += 1

            if len(points) >= 100:
                if self.client:
                    self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)
                points = []

        if points:
            if self.client:
                self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)

        return indexed

    async def search(
        self,
        query: str,
        repository_id: str,
        limit: int = 10,
        chunk_types: list[str] | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_collection()
        query_embedding = await self._get_embedding(query)

        if not self.client:
            return []

        from qdrant_client.http import models as qmodels

        must_conditions = [
            qmodels.FieldCondition(
                key="repository_id",
                match=qmodels.MatchValue(value=repository_id),
            )
        ]
        if chunk_types:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="chunk_type",
                    match=qmodels.MatchAny(any=chunk_types),
                )
            )
        if language:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="language",
                    match=qmodels.MatchValue(value=language),
                )
            )

        results = self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=query_embedding,
            query_filter=qmodels.Filter(must=must_conditions),
            limit=limit,
            with_payload=True,
        )

        return [
            {
                "score": hit.score,
                "file_path": hit.payload.get("file_path"),
                "chunk_type": hit.payload.get("chunk_type"),
                "language": hit.payload.get("language"),
                "symbol_name": hit.payload.get("symbol_name"),
                "content": hit.payload.get("content"),
                "start_line": hit.payload.get("start_line"),
                "end_line": hit.payload.get("end_line"),
            }
            for hit in results
        ]

    def delete_repository(self, repository_id: str) -> None:
        if not self.client:
           return
        from qdrant_client.http import models as qmodels
        self.client.delete(
           collection_name=self.settings.qdrant_collection,
           points_selector=qmodels.FilterSelector(
               filter=qmodels.Filter(
                   must=[
                       qmodels.FieldCondition(
                           key="repository_id",
                           match=qmodels.MatchValue(value=repository_id),
                       )
                   ]
               )
           ),
        )

    def delete_repository_file(self, repository_id: str, file_path: str) -> None:
        if not self.client:
           return
        from qdrant_client.http import models as qmodels
        self.client.delete(
           collection_name=self.settings.qdrant_collection,
           points_selector=qmodels.FilterSelector(
               filter=qmodels.Filter(
                   must=[
                       qmodels.FieldCondition(
                           key="repository_id",
                           match=qmodels.MatchValue(value=repository_id),
                       ),
                       qmodels.FieldCondition(
                           key="file_path",
                           match=qmodels.MatchValue(value=file_path),
                       ),
                   ]
               )
           ),
        )
