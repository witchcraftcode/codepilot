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

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class EmbeddingClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        # embeddings object may be sync; create lazily to avoid import-time provider deps
        try:
            from app.services.embedding_factory import get_embeddings

            self._embeddings = get_embeddings()
        except Exception:
            # In unit tests or environments missing provider libs, fall back to None
            self._embeddings = None

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, using cache for existing items and batching provider calls.

        Returns embeddings in the same order as texts.
        """
        if not texts:
            return []

        # First, compute hashes and consult cache
        hashes = [_content_hash(t) for t in texts]
        cached_tasks = [cache_service.get_embedding_cache(h) for h in hashes]
        cached_results = await asyncio.gather(*cached_tasks)

        results: List[List[float] | None] = [None] * len(texts)
        to_request: List[Tuple[int, str]] = []  # (index, text)
        for i, cached in enumerate(cached_results):
            if cached:
                results[i] = cached
            else:
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
                start = time.time()
                try:
                    provider_embeddings = await self._call_provider(list(strs))
                    latency = time.time() - start
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
                        await cache_service.set_embedding_cache(hashes[idx], emb)
                    break
                except Exception as exc:  # pragma: no cover - network/provider errors
                    if attempt > max_retries:
                        logger.exception("embedding_batch: exhausted retries for batch: %s", exc)
                        # Fill with zero vectors to preserve ordering
                        zero = [0.0] * getattr(self.settings, "vector_dimension", 1536)
                        for idx in indices:
                            results[idx] = zero
                        break
                    backoff = backoff_base * (2 ** (attempt - 1)) + (random.random() * 0.1)
                    logger.warning(
                        "embedding_batch: attempt %d failed, retrying in %.2fs: %s",
                        attempt,
                        backoff,
                        exc,
                    )
                    await asyncio.sleep(backoff)

        # At this point results should be fully populated
        final = [r if r is not None else [0.0] * getattr(self.settings, "vector_dimension", 1536) for r in results]
        return final

    async def _call_provider(self, texts: List[str]) -> List[List[float]]:
        """Call the underlying embeddings provider. Runs sync providers in a threadpool.

        Returns list of embedding vectors matching texts order.
        """
        if not self._embeddings:
            # No provider in tests/environment: return zero vectors
            return [[0.0] * self.settings.vector_dimension for _ in texts]

        # Many LangChain embedding classes expose async methods, but to be safe
        # call sync embed_documents in a threadpool.
        if hasattr(self._embeddings, "aembed_documents"):
            try:
                return await self._embeddings.aembed_documents(texts)
            except Exception:
                # fallback to sync
                pass

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._embeddings.embed_documents(list(texts)))
