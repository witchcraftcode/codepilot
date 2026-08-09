"""Hybrid retrieval engine combining semantic (Qdrant) and BM25 keyword retrieval,
then merging and reranking with a cross-encoder (configurable). The service is
repository-aware, language-aware, supports metadata filters, and emits latency
and precision logs.

Architecture:
- SemanticRetriever (VectorStore wrapper)
- KeywordRetriever (BM25 built from EmbeddingRecord content)
- CrossEncoderReranker (pluggable; default linear combiner)
- HybridRetrievalService - coordinates pipeline

Pipeline:
Query -> SemanticRetriever + KeywordRetriever -> Merge -> CrossEncoderRerank -> top-k

Note: This module does not call any LLM. Cross-encoder is a ranking model; the
default implementation is a lightweight combiner of signals. A true cross-encoder
can be plugged in by providing an object implementing rerank(query, candidates).
"""

import logging
import math
import re
import statistics
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from app.config import get_settings
from app.services.observability import record_retrieval, trace_span

from vectorstore.qdrant_store import VectorStore

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class BM25Okapi:
    """Minimal BM25 implementation for in-memory corpora.

    This is intentionally small and suitable for unit tests and moderate-sized
    repositories. For large-scale production, use a specialized search engine
    (Elasticsearch, Tantivy, Lucene, or Whoosh) with proper indexing.
    """

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = docs
        self.N = len(docs)
        self.doc_tokens = [tokenize(d) for d in docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avgdl = statistics.mean(self.doc_len) if self.doc_len else 0.0
        self.df = Counter()
        self.term_freqs = []

        for tokens in self.doc_tokens:
            freqs = Counter(tokens)
            self.term_freqs.append(freqs)
            for term in freqs.keys():
                self.df[term] += 1

    def score(self, query: str, index: int) -> float:
        q_tokens = tokenize(query)
        score = 0.0
        freqs = self.term_freqs[index]
        dl = self.doc_len[index]
        for q in q_tokens:
            if freqs.get(q, 0) == 0:
                continue
            df = self.df.get(q, 0)
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            tf = freqs[q]
            denom = tf + self.k1 * (1 - self.b + self.b * (dl / self.avgdl))
            score += idf * ((tf * (self.k1 + 1)) / denom)
        return score

    def get_top_n(self, query: str, n: int = 5) -> List[Tuple[int, float]]:
        scores = [(i, self.score(query, i)) for i in range(self.N)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:n]


class SemanticRetriever:
    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store or VectorStore()

    async def retrieve(self, repository_id: str, query: str, k: int = 10, chunk_types: Optional[List[str]] = None, language: Optional[str] = None, metadata_filter: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], int]:
        start = time.perf_counter()
        with trace_span("retrieval.semantic", repository_id=repository_id, limit=k):
            results = await self.vector_store.search(query=query, repository_id=repository_id, limit=k, chunk_types=chunk_types, language=language)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        record_retrieval("semantic", elapsed_ms)
        return results, elapsed_ms


class KeywordRetriever:
    """Builds an in-memory BM25 index for a repository's code chunks.

    For large repositories, pre-compute and persist the inverted index; here we
    load the embedding records' content_preview and run BM25 in memory.
    """

    def __init__(self, db: Any):
        self.db = db
        self._corpus_cache: Dict[str, List[Dict[str, Any]]] = {}

    async def _load_corpus(self, repository_id: UUID, language: Optional[str] = None, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Lazy import to avoid creating DB engines at module import time
        from app.models.embedding import EmbeddingRecord  # type: ignore

        # Load content previews for repository and optional language/metadata filters
        query = (await self.db.execute(
            EmbeddingRecord.__table__.select().where(EmbeddingRecord.repository_id == repository_id)
        )).all()
        # query returns Row objects; map to dict
        rows = [dict(row._mapping) for row in query]

        def match_metadata(row: Dict[str, Any]) -> bool:
            if language and row.get("language") and row.get("language") != language:
                return False
            if not metadata_filter:
                return True
            meta = row.get("metadata") or row.get("metadata_") or {}
            for k, v in metadata_filter.items():
                if meta.get(k) != v:
                    return False
            return True

        filtered = [
            {
                "id": str(r["id"]),
                "content": (r.get("content_preview") or "")[:5000],
                "file_path": r.get("file_path"),
                "language": r.get("language"),
                "symbol_name": r.get("symbol_name"),
                "chunk_type": r.get("chunk_type"),
                "content_hash": r.get("content_hash"),
                "metadata": r.get("metadata") or r.get("metadata_") or {},
            }
            for r in rows
            if match_metadata(r)
        ]
        return filtered

    async def retrieve(self, repository_id: UUID, query: str, top_n: int = 50, language: Optional[str] = None, metadata_filter: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], int]:
        start = time.perf_counter()
        with trace_span("retrieval.keyword", repository_id=str(repository_id), limit=top_n):
            corpus = await self._load_corpus(repository_id, language=language, metadata_filter=metadata_filter)
            docs = [d["content"] or "" for d in corpus]
            bm25 = BM25Okapi(docs)
            top = bm25.get_top_n(query, n=top_n)
        results = []
        for idx, score in top:
            entry = corpus[idx]
            entry = dict(entry)
            entry["bm25_score"] = score
            results.append(entry)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        record_retrieval("keyword", elapsed_ms)
        return results, elapsed_ms


class CrossEncoderReranker:
    """Pluggable reranker. Default implementation is a linear combiner of signals.

    A real cross-encoder model can be injected by providing an object with the
    same `rerank(query, candidates)` async method that returns re-scored candidates.
    """

    def __init__(self, alpha: float = 0.7, beta: float = 0.3):
        # alpha: weight for semantic score ; beta: weight for lexical bm25 score
        self.alpha = alpha
        self.beta = beta

    async def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        start = time.perf_counter()
        with trace_span("retrieval.rerank", candidates=len(candidates)):
            # normalize scores
            sem_scores = [c.get("score") or c.get("semantic_score") or 0.0 for c in candidates]
            bm25_scores = [c.get("bm25_score") or 0.0 for c in candidates]

            max_sem = max(sem_scores) if sem_scores else 1.0
            max_bm = max(bm25_scores) if bm25_scores else 1.0

            reranked = []
            q_tokens = set(tokenize(query))
            for c, s, b in zip(candidates, sem_scores, bm25_scores):
                norm_s = s / max_sem if max_sem else 0.0
                norm_b = b / max_bm if max_bm else 0.0
                # term overlap as small additional signal
                cont_tokens = set(tokenize(c.get("content") or ""))
                overlap = len(q_tokens & cont_tokens) / (len(q_tokens) or 1)
                score = self.alpha * norm_s + self.beta * norm_b + 0.05 * overlap
                new = dict(c)
                new["rerank_score"] = score
                reranked.append(new)

            reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        record_retrieval("rerank", elapsed_ms)
        return reranked, elapsed_ms


class HybridRetrievalService:
    def __init__(self, db: Any, vector_store: Optional[VectorStore] = None, reranker: Optional[CrossEncoderReranker] = None):
        self.db = db
        self.vector_store = vector_store or VectorStore()
        self.semantic = SemanticRetriever(self.vector_store)
        self.keyword = KeywordRetriever(db)
        self.reranker = reranker or CrossEncoderReranker()
        self.settings = get_settings()

    async def retrieve(self, repository_id: UUID, query: str, top_k: int = 5, chunk_types: Optional[List[str]] = None, language: Optional[str] = None, metadata_filter: Optional[Dict[str, Any]] = None, semantic_k: Optional[int] = None, keyword_k: Optional[int] = None) -> Dict[str, Any]:
        """Run hybrid retrieval pipeline and return top-k contexts with scores and metrics.

        Parameters
        - repository_id: repository UUID
        - query: user query
        - top_k: number of contexts to return after reranking
        - chunk_types, language, metadata_filter: used in semantic retrieval
        - semantic_k, keyword_k: optional overrides for number of candidates pulled from each retriever
        """
        repo_id_str = str(repository_id)
        semantic_k = semantic_k or (top_k * 5)
        keyword_k = keyword_k or (top_k * 10)

        overall_start = time.perf_counter()

        with trace_span("retrieval.hybrid", repository_id=repo_id_str, top_k=top_k):
            # Semantic retrieval
            sem_results, sem_latency_ms = await self.semantic.retrieve(repository_id=repo_id_str, query=query, k=semantic_k, chunk_types=chunk_types, language=language, metadata_filter=metadata_filter)

            # Keyword retrieval
            kw_results, kw_latency_ms = await self.keyword.retrieve(repository_id=repository_id, query=query, top_n=keyword_k, language=language, metadata_filter=metadata_filter)

        # Create candidate map keyed by content_hash or id
        cand_map: Dict[str, Dict[str, Any]] = {}

        for s in sem_results:
            key = s.get("sha256") or s.get("content_hash") or (s.get("file_path") + ":" + str(s.get("start_line")))
            entry = dict(s)
            entry["semantic_score"] = s.get("score") or s.get("similarity") or 0.0
            entry.setdefault("bm25_score", 0.0)
            entry.setdefault("content", s.get("content") or s.get("content_preview") or "")
            cand_map[key] = entry

        for k in kw_results:
            key = k.get("content_hash") or k.get("id")
            if key in cand_map:
                cand_map[key]["bm25_score"] = k.get("bm25_score", 0.0)
            else:
                entry = dict(k)
                entry.setdefault("semantic_score", 0.0)
                entry.setdefault("content", k.get("content") or "")
                cand_map[key] = entry

        candidates = list(cand_map.values())

        # Log counts and overlap
        semantic_keys = set([s.get("sha256") or s.get("content_hash") or (s.get("file_path") + ":" + str(s.get("start_line"))) for s in sem_results])
        kw_keys = set([k.get("content_hash") or k.get("id") for k in kw_results])
        overlap = len(semantic_keys & kw_keys)
        precision_proxy = overlap / (len(semantic_keys) or 1)

        # Rerank candidates
        reranked, rerank_latency_ms = await self.reranker.rerank(query, candidates)

        top = reranked[:top_k]

        overall_latency_ms = int((time.perf_counter() - overall_start) * 1000)
        record_retrieval("hybrid_total", overall_latency_ms)

        # Build response
        response = {
            "query": query,
            "repository_id": repo_id_str,
            "top_k": top_k,
            "results": [
                {
                    "content": r.get("content"),
                    "file_path": r.get("file_path"),
                    "language": r.get("language"),
                    "symbol_name": r.get("symbol_name"),
                    "chunk_type": r.get("chunk_type"),
                    "start_line": r.get("start_line"),
                    "end_line": r.get("end_line"),
                    "sha256": r.get("sha256") or r.get("content_hash"),
                    "semantic_score": r.get("semantic_score"),
                    "bm25_score": r.get("bm25_score"),
                    "rerank_score": r.get("rerank_score"),
                }
                for r in top
            ],
            "metrics": {
                "semantic_latency_ms": sem_latency_ms,
                "keyword_latency_ms": kw_latency_ms,
                "rerank_latency_ms": rerank_latency_ms,
                "overall_latency_ms": overall_latency_ms,
                "semantic_candidates": len(sem_results),
                "keyword_candidates": len(kw_results),
                "merged_candidates": len(candidates),
                "semantic_keyword_overlap": overlap,
                "precision_proxy": precision_proxy,
            },
        }

        # Structured logs for observability
        logger.info("hybrid_retrieval: repo=%s query_len=%d top_k=%d metrics=%s",
                    repo_id_str, len(query), top_k, response["metrics"])

        return response
