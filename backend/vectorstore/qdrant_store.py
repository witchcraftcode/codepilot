"""Qdrant vector store integration for code chunk retrieval."""

import hashlib
import uuid
import time
import logging
from typing import Any

from app.config import get_settings
from app.services.cache import cache_service
from parsers.chunker import CodeChunk

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self) -> None:
        # Lazy import of qdrant to avoid import-time dependency during unit tests
        try:
            from qdrant_client import QdrantClient
        except Exception:  # pragma: no cover - environment may not have qdrant
            QdrantClient = None  # type: ignore

        self.settings = get_settings()
        self.client = QdrantClient(url=self.settings.qdrant_url) if QdrantClient else None
        # Use the new EmbeddingClient wrapper for batching, caching and retries
        try:
            from app.services.embedding_client import EmbeddingClient

            self.embedding_client = EmbeddingClient()
        except Exception:
            self.embedding_client = None

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

    async def index_chunks(self, repository_id: str, chunks: list[CodeChunk]) -> int:
        """Index multiple code chunks in Qdrant using batched embeddings.

        This implementation batches embeddings across chunks, uses Redis cache for
        embeddings, logs latency and vector counts, and upserts points in Qdrant in
        batches to reduce overhead.
        """
        self.ensure_collection()
        from qdrant_client.http import models as qmodels

        # Filter out very small chunks and prepare payloads
        items = []  # tuples of (chunk, content)
        for chunk in chunks:
            content = chunk.content.strip()
            if len(content) < 10:
                continue
            items.append((chunk, content))

        if not items:
            return 0

        contents = [c for (_, c) in items]

        # Obtain embeddings in batches via the EmbeddingClient
        start_ts = time.time()
        embeddings = await (self.embedding_client.embed_batch(contents) if self.embedding_client else [[0.0] * self.settings.vector_dimension for _ in contents])
        elapsed = time.time() - start_ts
        logger.info("embeddings_obtained: repository=%s provider=%s count=%d latency=%.3fs",
                    repository_id,
                    getattr(self.settings, "embedding_provider", None),
                    len(embeddings),
                    elapsed)

        points: list[qmodels.PointStruct] = []
        indexed = 0

        for (chunk, content), emb in zip(items, embeddings):
            point_id = str(uuid.uuid4())
            payload = {
                "repository_id": repository_id,
                "file_path": chunk.file_path,
                "language": chunk.language,
                "symbol_name": chunk.symbol_name,
                "symbol_type": chunk.chunk_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "sha256": self._content_hash(content),
                "content_preview": content[:2000],
            }
            points.append(qmodels.PointStruct(id=point_id, vector=emb, payload=payload))
            indexed += 1

            # Flush to Qdrant in moderate sized batches
            if len(points) >= 256:
                if self.client:
                    self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)
                points = []

        if points and self.client:
            self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)

        logger.info("vectors_indexed: repository=%s provider=%s vectors=%d",
                    repository_id,
                    getattr(self.settings, "embedding_provider", None),
                    indexed)

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
        # Reuse embedding client to get query embedding
        query_embedding = await (self.embedding_client.embed_batch([query])[0] if self.embedding_client else [0.0] * self.settings.vector_dimension)

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
                "content": hit.payload.get("content_preview") or hit.payload.get("content"),
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
