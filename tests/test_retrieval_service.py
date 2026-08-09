import asyncio
import time
from uuid import uuid4

from app.services.retrieval_service import RetrievalService
from vectorstore.qdrant_store import VectorStore


def test_retrieval_service_returns_results_and_latency(monkeypatch):
    sample_results = [
        {
            "score": 0.95,
            "file_path": "src/app.py",
            "chunk_type": "function",
            "language": "python",
            "symbol_name": "hello",
            "content": "def hello():\n    return 'world'",
            "start_line": 1,
            "end_line": 2,
        }
    ]

    async def fake_search(self, query, repository_id, limit=5, chunk_types=None, language=None):
        await asyncio.sleep(0.01)  # simulate some latency
        return sample_results

    monkeypatch.setattr(VectorStore, "search", fake_search)

    service = RetrievalService()
    start = time.perf_counter()
    out = asyncio.run(service.retrieve(uuid4(), "hello", k=1))
    end = time.perf_counter()

    assert "retrieved" in out
    assert isinstance(out["retrieved"], list)
    assert out["retrieved"] == sample_results
    assert "latency_ms" in out
    assert out["latency_ms"] >= 1
    # Ensure measured latency is reasonable compared to actual elapsed time
    assert out["latency_ms"] <= int((end - start) * 1000) + 100
