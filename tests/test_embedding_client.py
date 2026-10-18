import asyncio

import pytest

from app.services.embedding_client import EmbeddingClient


class DummyEmb:
    def __init__(self, dim=4):
        self.dim = dim

    def embed_documents(self, texts):
        # deterministic embedding for tests
        return [[float(len(t) + i % 4) for _ in range(self.dim)] for i, t in enumerate(texts)]


def test_embed_batch_with_cache_and_provider(monkeypatch):
    async def _run():
        client = EmbeddingClient()

        # patch internal embeddings to our dummy
        client._embeddings = DummyEmb(dim=3)
        client.settings.vector_dimension = 3

        # patch cache_service to simulate cache hit for first item and miss for others
        called_get = {}

        import hashlib

        cached_hash = hashlib.sha256("cached-abc".encode()).hexdigest()

        async def fake_get(key):
            if key == f"emb:{cached_hash}":
                return [1.0, 2.0, 3.0]
            return None

        async def fake_set(key, value):
            called_get[key] = value

        from app.services.cache import cache_service as _cache
        monkeypatch.setattr(_cache, "get_embedding_cache", fake_get)
        monkeypatch.setattr(_cache, "set_embedding_cache", fake_set)
        # Also ensure the embedding_client module reference is patched
        monkeypatch.setattr("app.services.embedding_client.cache_service.get_embedding_cache", fake_get)
        monkeypatch.setattr("app.services.embedding_client.cache_service.set_embedding_cache", fake_set)

        texts = ["cached-abc", "one", "two"]

        embeddings = await client.embed_batch(texts)

        assert len(embeddings) == 3
        # first one came from cache
        assert embeddings[0] == [1.0, 2.0, 3.0]
        # others come from provider and subsequently cached
        assert any(k.startswith("emb:") for k in called_get.keys())

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_embedding_provider_failure_raises_without_zero_vectors(monkeypatch):
    client = EmbeddingClient()
    client.settings.vector_dimension = 4
    client.settings.embedding_max_retries = 0
    client._embeddings = DummyEmb(dim=4)

    async def cache_miss(_key):
        return None

    async def cache_set(_key, _value):
        return None

    async def provider_failure(_texts):
        raise OSError("provider unavailable")

    monkeypatch.setattr("app.services.embedding_client.cache_service.get_embedding_cache", cache_miss)
    monkeypatch.setattr("app.services.embedding_client.cache_service.set_embedding_cache", cache_set)
    monkeypatch.setattr(client, "_call_provider", provider_failure)

    with pytest.raises(RuntimeError, match="Embedding provider failed after retries"):
        await client.embed_batch(["source text"])


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_not_cached_or_returned(monkeypatch):
    client = EmbeddingClient()
    client.settings.vector_dimension = 4
    client.settings.embedding_max_retries = 0
    cached = []

    async def cache_miss(_key):
        return None

    async def cache_set(_key, _value):
        cached.append(_value)

    async def wrong_dimension(_texts):
        return [[0.0, 0.0, 0.0]]

    monkeypatch.setattr("app.services.embedding_client.cache_service.get_embedding_cache", cache_miss)
    monkeypatch.setattr("app.services.embedding_client.cache_service.set_embedding_cache", cache_set)
    monkeypatch.setattr(client, "_call_provider", wrong_dimension)

    with pytest.raises(RuntimeError, match="Embedding provider failed after retries") as exc_info:
        await client.embed_batch(["source text"])

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert cached == []
