import asyncio

from vectorstore.qdrant_store import VectorStore


class DummyEmbeddingClient:
    async def embed_batch(self, texts):
        return [[float(len(t)) for _ in range(8)] for t in texts]


def test_index_chunks_counts(monkeypatch):
    async def _run():
        # Create a minimal CodeChunk-like object
        class Chunk:
            def __init__(self, content, file_path="f.py", language="python", symbol_name="s", chunk_type="function", start_line=1, end_line=2):
                self.content = content
                self.file_path = file_path
                self.language = language
                self.symbol_name = symbol_name
                self.chunk_type = chunk_type
                self.start_line = start_line
                self.end_line = end_line

        chunks = [Chunk("def a(): pass"), Chunk("# comment"), Chunk("x = 1\n\n\n")]

        vs = VectorStore()
        # Patch embedding client
        vs.embedding_client = DummyEmbeddingClient()

        count = await vs.index_chunks("repo-1", chunks)
        # one chunk is a short comment, two others valid -> should be 2
        assert count == 2

    asyncio.run(_run())
