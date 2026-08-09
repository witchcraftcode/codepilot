import time
import pytest

from app.services.hybrid_retrieval import BM25Okapi, CrossEncoderReranker, HybridRetrievalService


def test_bm25_basic_ranking():
    docs = [
        "def add(a, b): return a + b",
        "# this is a comment",
        "def multiply(x, y): return x * y",
        "class Worker: pass",
    ]
    bm = BM25Okapi(docs)
    top = bm.get_top_n("add function", n=2)
    # top result should be doc 0 (add)
    assert top[0][0] == 0


def test_reranker_combines_scores():
    reranker = CrossEncoderReranker(alpha=0.6, beta=0.4)
    query = "add numbers"
    candidates = [
        {"content": "def add(a,b): return a+b", "score": 0.9, "bm25_score": 1.0},
        {"content": "def multiply(a,b): return a*b", "score": 0.7, "bm25_score": 0.2},
        {"content": "some comment", "score": 0.1, "bm25_score": 0.05},
    ]

    import asyncio
    reranked, latency = asyncio.run(reranker.rerank(query, candidates))
    assert len(reranked) == 3
    # first should be add
    assert "add" in reranked[0]["content"]
    assert latency >= 0


class DummySemantic:
    async def retrieve(self, repository_id, query, k=10, **kwargs):
        # return list of dicts like qdrant payloads
        return ([
            {"sha256": "h1", "content": "def add(a,b): return a+b", "score": 0.95, "file_path": "f.py", "start_line": 1, "end_line": 3},
            {"sha256": "h2", "content": "def mult(x,y): return x*y", "score": 0.6, "file_path": "f.py", "start_line": 10, "end_line": 12},
        ], 10)


class DummyKeyword:
    async def retrieve(self, repository_id, query, top_n=50, **kwargs):
        return ([
            {"id": "k1", "content": "def add(a,b): return a+b", "content_hash": "h1", "bm25_score": 3.2, "file_path": "f.py"},
            {"id": "k3", "content": "utility function", "content_hash": "h3", "bm25_score": 1.1, "file_path": "utils.py"},
        ], 5)


def test_hybrid_retrieval_merges_and_reranks(monkeypatch):
    # Prepare a HybridRetrievalService with monkeypatched subcomponents
    class DummyDB:
        pass

    service = HybridRetrievalService(db=DummyDB())
    # patch semantic and keyword retrievers
    service.semantic = DummySemantic()
    service.keyword = DummyKeyword()

    # run retrieval
    import asyncio
    resp = asyncio.run(service.retrieve("repo-1", "add numbers", top_k=2))

    # response structure
    assert resp["repository_id"] == "repo-1"
    assert len(resp["results"]) == 2
    # top result should correspond to add
    assert "add" in resp["results"][0]["content"]
    # metrics present
    assert "metrics" in resp
    assert resp["metrics"]["merged_candidates"] >= 2


def test_benchmark_retrieval(monkeypatch):
    # Benchmark: run retrieval multiple times and check average latencies are recorded
    class DummyDB:
        pass

    service = HybridRetrievalService(db=DummyDB())
    service.semantic = DummySemantic()
    service.keyword = DummyKeyword()

    runs = 5
    total = 0
    for i in range(runs):
        start = time.perf_counter()
        import asyncio
        resp = asyncio.run(service.retrieve("repo-1", f"query {i}", top_k=1))
        total += resp["metrics"]["overall_latency_ms"]
    avg = total / runs
    print(f"Average retrieval latency (ms): {avg}")
    assert avg >= 0
