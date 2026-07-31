"""RAGAS-based evaluation framework for retrieval and generation quality."""

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalMetrics:
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0


@dataclass
class RAGMetrics:
    faithfulness: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    answer_relevancy: float = 0.0


@dataclass
class PerformanceMetrics:
    agent_execution_ms: int = 0
    retrieval_ms: int = 0
    llm_latency_ms: int = 0
    total_ms: int = 0


@dataclass
class CostMetrics:
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass
class EvaluationReport:
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    rag: RAGMetrics = field(default_factory=RAGMetrics)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    cost: CostMetrics = field(default_factory=CostMetrics)
    metadata: dict[str, Any] = field(default_factory=dict)


def compute_precision_at_k(relevant: set[str], retrieved: list[str], k: int = 5) -> float:
    if not retrieved[:k]:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / k


def compute_recall_at_k(relevant: set[str], retrieved: list[str], k: int = 5) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / len(relevant)


def compute_mrr(relevant: set[str], retrieved: list[str]) -> float:
    for i, r in enumerate(retrieved, 1):
        if r in relevant:
            return 1.0 / i
    return 0.0


async def evaluate_with_ragas(
    questions: list[str],
    contexts: list[list[str]],
    answers: list[str],
    ground_truths: list[str] | None = None,
) -> RAGMetrics:
    """Run RAGAS evaluation when the library and API keys are available."""
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        data = {
            "question": questions,
            "contexts": contexts,
            "answer": answers,
        }
        if ground_truths:
            data["ground_truth"] = ground_truths

        dataset = Dataset.from_dict(data)
        metrics = [faithfulness, context_precision, context_recall, answer_relevancy]
        result = evaluate(dataset, metrics=metrics)

        return RAGMetrics(
            faithfulness=float(result.get("faithfulness", 0)),
            context_precision=float(result.get("context_precision", 0)),
            context_recall=float(result.get("context_recall", 0)),
            answer_relevancy=float(result.get("answer_relevancy", 0)),
        )
    except ImportError:
        return RAGMetrics()
    except Exception:
        return RAGMetrics()


async def run_evaluation_suite(
    repository_id: str,
    test_queries: list[dict[str, Any]],
) -> EvaluationReport:
    """Run full evaluation suite against a indexed repository."""
    import time

    from vectorstore.qdrant_store import VectorStore

    store = VectorStore()
    report = EvaluationReport()

    retrieval_start = time.time()
    all_precision = []
    all_recall = []
    all_mrr = []

    for query_item in test_queries:
        query = query_item["query"]
        relevant_files = set(query_item.get("relevant_files", []))

        results = await store.search(query=query, repository_id=repository_id, limit=10)
        retrieved_files = [r["file_path"] for r in results]

        all_precision.append(compute_precision_at_k(relevant_files, retrieved_files))
        all_recall.append(compute_recall_at_k(relevant_files, retrieved_files))
        all_mrr.append(compute_mrr(relevant_files, retrieved_files))

    report.performance.retrieval_ms = int((time.time() - retrieval_start) * 1000)

    if all_precision:
        report.retrieval.precision_at_k = sum(all_precision) / len(all_precision)
        report.retrieval.recall_at_k = sum(all_recall) / len(all_recall)
        report.retrieval.mrr = sum(all_mrr) / len(all_mrr)

    return report


if __name__ == "__main__":
    sample_queries = [
        {"query": "authentication login", "relevant_files": ["auth/login.py", "middleware/auth.py"]},
        {"query": "database connection pool", "relevant_files": ["db/session.py"]},
    ]
    report = asyncio.run(run_evaluation_suite("test-repo-id", sample_queries))
    print(f"Precision@5: {report.retrieval.precision_at_k:.3f}")
    print(f"Recall@5: {report.retrieval.recall_at_k:.3f}")
    print(f"MRR: {report.retrieval.mrr:.3f}")
