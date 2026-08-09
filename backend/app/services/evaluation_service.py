"""Evaluation service for repository retrieval and RAG benchmarking."""

import os
import sys
from typing import Any, Dict, List
from uuid import UUID

# Ensure repository-root evaluation utilities are importable when backend/ is the package root.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from langchain_core.messages import HumanMessage, SystemMessage
except Exception:
    class HumanMessage:
        def __init__(self, content: str):
            self.content = content

    class SystemMessage:
        def __init__(self, content: str):
            self.content = content

from app.config import get_settings
from app.models.repository import Repository
from app.services.hybrid_retrieval import HybridRetrievalService
from app.services.llm_factory import get_llm
from app.services.observability import extract_token_usage, measured_llm_ainvoke
from evaluation.ragas_eval import (
    EvaluationReport,
    build_context,
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
    estimate_cost,
    evaluate_with_ragas,
)


class EvaluationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()
        self.hybrid = HybridRetrievalService(db=db)

    async def evaluate_repository(
        self,
        repository_id: UUID,
        test_queries: List[Dict[str, Any]],
        top_k: int = 5,
        include_baseline: bool = True,
    ) -> EvaluationReport:
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = result.scalar_one_or_none()
        if not repo:
            raise ValueError("Repository not found")

        report = EvaluationReport(metadata={
            "repository_id": str(repository_id),
            "repository_name": repo.name,
            "sample_count": len(test_queries),
        })

        retrieval_precisions: List[float] = []
        retrieval_recalls: List[float] = []
        retrieval_mrrs: List[float] = []
        retrieval_latencies: List[int] = []
        llm_latencies: List[int] = []
        llm_tokens: List[int] = []

        current_answers: List[str] = []
        baseline_answers: List[str] = []
        context_batches: List[List[str]] = []
        ground_truths: List[str] = []

        for query_item in test_queries:
            query_text = query_item.get("query", "")
            relevant_files = set(query_item.get("relevant_files", []))
            ground_truth = query_item.get("ground_truth")

            retrieval = await self.hybrid.retrieve(repository_id, query_text, top_k=top_k)
            retrieval_latencies.append(retrieval["metrics"].get("overall_latency_ms", 0))

            retrieved_files = [r.get("file_path") for r in retrieval.get("results", []) if r.get("file_path")]
            retrieval_precisions.append(compute_precision_at_k(relevant_files, retrieved_files, k=top_k))
            retrieval_recalls.append(compute_recall_at_k(relevant_files, retrieved_files, k=top_k))
            retrieval_mrrs.append(compute_mrr(relevant_files, retrieved_files))

            candidates = retrieval.get("results", [])
            context_batches.append([c.get("content", "") for c in candidates])

            context_text = build_context(candidates)
            answer, latency_ms, tokens = await self._generate_grounded_answer(query_text, context_text)
            llm_latencies.append(latency_ms)
            llm_tokens.append(tokens)
            current_answers.append(answer)

            if include_baseline:
                baseline_answer, baseline_latency, baseline_tokens = await self._generate_baseline_answer(query_text, repo)
                baseline_answers.append(baseline_answer)
                report.baseline.average_latency_ms += baseline_latency
                report.baseline.total_tokens += baseline_tokens

            if ground_truth is not None:
                ground_truths.append(ground_truth)

        report.retrieval.precision_at_k = float(sum(retrieval_precisions) / len(retrieval_precisions)) if retrieval_precisions else 0.0
        report.retrieval.recall_at_k = float(sum(retrieval_recalls) / len(retrieval_recalls)) if retrieval_recalls else 0.0
        report.retrieval.mrr = float(sum(retrieval_mrrs) / len(retrieval_mrrs)) if retrieval_mrrs else 0.0
        report.performance.retrieval_ms = int(sum(retrieval_latencies) / len(retrieval_latencies)) if retrieval_latencies else 0
        report.performance.llm_latency_ms = int(sum(llm_latencies) / len(llm_latencies)) if llm_latencies else 0
        report.performance.total_ms = report.performance.retrieval_ms + report.performance.llm_latency_ms
        report.cost.tokens_used += sum(llm_tokens)
        report.cost.cost_usd = estimate_cost(report.cost.tokens_used, self.settings.llm_provider.value)
        report.baseline.average_latency_ms = int(report.baseline.average_latency_ms / len(baseline_answers)) if baseline_answers else 0
        report.baseline.answers = baseline_answers
        report.baseline.cost_usd = estimate_cost(report.baseline.total_tokens, self.settings.llm_provider.value)

        if ground_truths:
            report.rag = await evaluate_with_ragas(
                [item["query"] for item in test_queries],
                context_batches,
                current_answers,
                ground_truths if len(ground_truths) == len(test_queries) else None,
            )
        else:
            report.rag = await evaluate_with_ragas(
                [item["query"] for item in test_queries],
                context_batches,
                current_answers,
            )

        if baseline_answers:
            baseline_rag = await evaluate_with_ragas(
                [item["query"] for item in test_queries],
                context_batches,
                baseline_answers,
                ground_truths if len(ground_truths) == len(test_queries) else None,
            )
            report.baseline.faithfulness = baseline_rag.faithfulness
            report.baseline.context_precision = baseline_rag.context_precision
            report.baseline.context_recall = baseline_rag.context_recall
            report.baseline.answer_relevancy = baseline_rag.answer_relevancy
            report.comparison = {
                "answer_relevancy_delta": round(report.rag.answer_relevancy - report.baseline.answer_relevancy, 4),
                "cost_delta_usd": round(report.cost.cost_usd - report.baseline.cost_usd, 6),
                "latency_delta_ms": report.performance.llm_latency_ms - report.baseline.average_latency_ms,
            }

        if hasattr(self.settings, "llm_provider"):
            report.metadata["provider"] = self.settings.llm_provider.value

        report.metadata["memory_usage_mb"] = self._get_memory_usage_mb()
        return report

    async def _generate_grounded_answer(self, query: str, context: str) -> tuple[str, int, int]:
        prompt = (
            "You are CodePilot AI. Answer ONLY from the provided context. "
            "If the answer is not present, respond exactly: 'I don't know based on the repository code.'"
        )
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"CONTEXT:\n{context}\n\nQuestion: {query}"),
        ]
        return await self._invoke_llm(messages)

    async def _generate_baseline_answer(self, query: str, repo: Repository) -> tuple[str, int, int]:
        repo_summary = (
            f"Repository name: {repo.name}\n"
            f"Languages: {repo.languages or {}}\n"
            f"Frameworks: {repo.frameworks or []}\n"
            f"File count: {repo.file_count}\n"
        )
        prompt = (
            "You are CodePilot AI. You do not have direct repository context. "
            "Answer only if the repository metadata clearly implies the answer. "
            "Otherwise respond exactly: 'I don't know based on the repository code.'"
        )
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Repository metadata:\n{repo_summary}\nQuestion: {query}"),
        ]
        return await self._invoke_llm(messages)

    async def _invoke_llm(self, messages: List[Any]) -> tuple[str, int, int]:
        llm = get_llm(temperature=0.0, max_tokens=512)
        resp, latency_ms, tokens, _ = await measured_llm_ainvoke(llm, messages, operation="evaluation")
        content = getattr(resp, "content", str(resp))
        tokens = tokens or self._extract_token_usage(resp)
        return str(content), latency_ms, tokens

    def _extract_token_usage(self, response: Any) -> int:
        return extract_token_usage(response)

    def _get_memory_usage_mb(self) -> float:
        try:
            import resource

            return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
        except Exception:
            return 0.0
