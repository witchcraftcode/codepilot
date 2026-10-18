"""Embedding client with provider abstraction, batching, Redis caching, retries and metrics.

This module wraps configured embedding providers (OpenAI, BGE) and provides an async
batching interface suitable for production. It leverages the existing embedding_factory
for provider initialization, uses the cache_service for per-content caching, and
implements exponential-backoff retry for provider calls.
"""

import asyncio
import hashlib
import logging
import math
import time
import random
from typing import List, Tuple

from app.config import get_settings
from app.services.cache import cache_service
from app.services.observability import record_cache, record_embedding, trace_span

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class EmbeddingClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        # Provider initialization errors must surface; a missing model cannot be
        # represented as a valid embedding without corrupting retrieval data.
        from app.services.embedding_factory import get_embeddings

        self._embeddings = get_embeddings()

    def _validate_vectors(self, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise ValueError(
                f"Embedding provider returned {len(vectors)} vectors for {expected_count} inputs"
            )
        expected_dimension = self.settings.vector_dimension
        if any(len(vector) != expected_dimension for vector in vectors):
            actual_dimensions = sorted({len(vector) for vector in vectors})
            raise ValueError(
                f"Embedding dimension mismatch: configured {expected_dimension}, provider returned {actual_dimensions}"
            )

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, using cache for existing items and batching provider calls.

        Returns embeddings in the same order as texts.
        """
        if not texts:
            return []

        # First, compute hashes and consult cache
        hashes = [_content_hash(t) for t in texts]
        cache_keys = [f"emb:{h}" for h in hashes]
        with trace_span("embedding.cache_lookup", count=len(texts)):
            cached_tasks = [cache_service.get_embedding_cache(key) for key in cache_keys]
            cached_results = await asyncio.gather(*cached_tasks)

        results: List[List[float] | None] = [None] * len(texts)
        to_request: List[Tuple[int, str]] = []  # (index, text)
        for i, cached in enumerate(cached_results):
            if cached:
                self._validate_vectors([cached], 1)
                record_cache("embedding", True)
                results[i] = cached
            else:
                record_cache("embedding", False)
                to_request.append((i, texts[i]))

        if not to_request:
            logger.debug("All embeddings found in cache, returning %d items", len(results))
            return [r for r in results if r is not None]

        # Batch provider calls
        batch_size = getattr(self.settings, "embedding_batch_size", 64)
        max_retries = getattr(self.settings, "embedding_max_retries", 3)
        backoff_base = getattr(self.settings, "embedding_backoff_base", 0.5)

        # Build batches of (indices, texts)
        batches: List[List[Tuple[int, str]]] = []
        for i in range(0, len(to_request), batch_size):
            batches.append(to_request[i : i + batch_size])

        # For each batch, call provider with retries
        for batch in batches:
            indices, strs = zip(*batch)
            attempt = 0
            while True:
                attempt += 1
                start = time.perf_counter()
                try:
                    with trace_span("embedding.provider", provider=str(self.settings.embedding_provider.value), count=len(strs)):
                        provider_embeddings = await self._call_provider(list(strs))
                    self._validate_vectors(provider_embeddings, len(strs))
                    latency = time.perf_counter() - start
                    record_embedding(str(self.settings.embedding_provider.value), "embed_batch", latency * 1000)
                    logger.info(
                        "embedding_batch: provider=%s batch_size=%d latency=%.3fs provider_model=%s",
                        self.settings.embedding_provider.value if getattr(self.settings, "embedding_provider", None) else None,
                        len(provider_embeddings),
                        latency,
                        getattr(self.settings, "embedding_model", None),
                    )

                    # store in cache and fill results
                    for idx, emb in zip(indices, provider_embeddings):
                        results[idx] = emb
                        await cache_service.set_embedding_cache(cache_keys[idx], emb)
                    break
                except Exception as exc:  # pragma: no cover - network/provider errors
                    if attempt > max_retries:
                        logger.error(
                            "embedding_batch: provider failed after %d attempts",
                            attempt,
                        )
                        raise RuntimeError(
                            "Embedding provider failed after retries"
                        ) from exc
                    backoff = backoff_base * (2 ** (attempt - 1)) + (random.random() * 0.1)
                    logger.warning(
                        "embedding_batch: provider attempt %d failed; retrying in %.2fs",
                        attempt,
                        backoff,
                    )
                    await asyncio.sleep(backoff)

        if any(result is None for result in results):
            raise RuntimeError("Embedding batch completed without a result for every input")
        return [result for result in results if result is not None]

    async def _call_provider(self, texts: List[str]) -> List[List[float]]:
        """Call the underlying embeddings provider. Runs sync providers in a threadpool.

        Returns list of embedding vectors matching texts order.
        """
        if not self._embeddings:
            raise RuntimeError("Configured embedding provider is unavailable")

        # Many LangChain embedding classes expose async methods, but to be safe
        # call sync embed_documents in a threadpool.
        if hasattr(self._embeddings, "aembed_documents"):
            return await self._embeddings.aembed_documents(texts)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._embeddings.embed_documents(list(texts)))
