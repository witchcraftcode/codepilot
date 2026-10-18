"""Qdrant vector store integration for code chunk retrieval."""

import hashlib
import uuid
import time
import logging
from typing import Any

from app.config import get_settings
from app.services.observability import record_qdrant, trace_span
from parsers.chunker import CodeChunk

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self) -> None:
        from qdrant_client import QdrantClient
        self.settings = get_settings()
        self.client = QdrantClient(
            url=self.settings.qdrant_url,
            api_key=self.settings.qdrant_api_key,
        )
        from app.services.embedding_client import EmbeddingClient

        self.embedding_client = EmbeddingClient()


    def ensure_collection(self) -> None:
        if not self.client:
            raise RuntimeError("Qdrant client is unavailable")

        from qdrant_client.http import models as qmodels
        from qdrant_client.http.exceptions import ResponseHandlingException

        collection_name = self.settings.qdrant_collection

        try:
            collections = [
                c.name for c in self.client.get_collections().collections
            ]
        except ResponseHandlingException as exc:
            logger.warning("Qdrant collection check failed")
            raise RuntimeError("Could not inspect Qdrant collections") from exc

        if collection_name not in collections:
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=self.settings.vector_dimension,
                    distance=qmodels.Distance.COSINE,
                ),
            )

        # Create any payload indexes required by repository filtering.
        collection_info = self.client.get_collection(collection_name)
        vector_config = collection_info.config.params.vectors
        configured_dimension = getattr(vector_config, "size", None)
        if configured_dimension is None and isinstance(vector_config, dict):
            configured_dimension = vector_config.get("size")
        if configured_dimension is None:
            raise RuntimeError("Qdrant collection uses an unsupported named-vector configuration")
        if configured_dimension != self.settings.vector_dimension:
            raise RuntimeError(
                f"Qdrant collection dimension {configured_dimension} does not match configured dimension {self.settings.vector_dimension}"
            )
        payload_schema = collection_info.payload_schema or {}

        required_indexes = {
            "repository_id": qmodels.PayloadSchemaType.KEYWORD,
            "file_path": qmodels.PayloadSchemaType.KEYWORD,
            "language": qmodels.PayloadSchemaType.KEYWORD,
            "chunk_type": qmodels.PayloadSchemaType.KEYWORD,
        }

        for field_name, field_schema in required_indexes.items():
            if field_name not in payload_schema:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
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
        if self.client is None:
            raise RuntimeError("Qdrant client is unavailable")

        # Filter out very small chunks and prepare payloads
        items = []  # tuples of (chunk, content)
        for chunk in chunks:
            content = chunk.content.strip()
            if not content or (len(content) < 10 and content.startswith("#")):
                continue
            items.append((chunk, content))

        if not items:
            return 0

        contents = [c for (_, c) in items]

        # Obtain embeddings in batches via the EmbeddingClient
        start_ts = time.time()
        embeddings = await self.embedding_client.embed_batch(contents)
        if len(embeddings) != len(items) or any(
            len(embedding) != self.settings.vector_dimension
            for embedding in embeddings
        ):
            raise RuntimeError("Embedding provider returned vectors incompatible with Qdrant")
        elapsed = time.time() - start_ts
        logger.info("embeddings_obtained: repository=%s provider=%s count=%d latency=%.3fs",
                    repository_id,
                    getattr(self.settings, "embedding_provider", None),
                    len(embeddings),
                    elapsed)

        from qdrant_client.http import models as qmodels

        points: list[qmodels.PointStruct] = []
        indexed = 0

        for (chunk, content), emb in zip(items, embeddings):
            point_id = str(uuid.uuid4())
            payload = {
                "repository_id": repository_id,
                "file_path": chunk.file_path,
                "language": chunk.language,
                "symbol_name": chunk.symbol_name,
                "chunk_type": chunk.chunk_type,
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
                    start = time.perf_counter()
                    with trace_span("qdrant.upsert", operation="upsert", points=len(points)):
                        self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)
                    record_qdrant("upsert", int((time.perf_counter() - start) * 1000))
                points = []

        if points and self.client:
            start = time.perf_counter()
            with trace_span("qdrant.upsert", operation="upsert", points=len(points)):
                self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)
            record_qdrant("upsert", int((time.perf_counter() - start) * 1000))

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
        if self.client is None:
            raise RuntimeError("Qdrant client is unavailable")
        embeddings = await self.embedding_client.embed_batch([query])
        query_embedding = embeddings[0]

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

        start = time.perf_counter()
        with trace_span("qdrant.search", operation="search", repository_id=repository_id, limit=limit):
            response = self.client.query_points(
                collection_name=self.settings.qdrant_collection,
                query=query_embedding,
                query_filter=qmodels.Filter(must=must_conditions),
                limit=limit,
                with_payload=True,
            )
            results = response.points
        record_qdrant("search", int((time.perf_counter() - start) * 1000))

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

        self.ensure_collection()

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
