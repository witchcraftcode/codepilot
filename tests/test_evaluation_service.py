import asyncio
from uuid import uuid4

from app.services.evaluation_service import EvaluationService
from evaluation.ragas_eval import EvaluationReport


class DummyRepo:
    def __init__(self):
        self.name = "test-repo"
        self.languages = {"python": 100}
        self.frameworks = ["fastapi"]
        self.file_count = 10


class DummyDBResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class DummyDB:
    async def execute(self, query):
        return DummyDBResult(DummyRepo())


class DummyHybrid:
    async def retrieve(self, repository_id, query, top_k=5):
        return {
            "results": [
                {
                    "file_path": "app.py",
                    "content": "def hello():\n    return 'world'",
                    "start_line": 1,
                    "end_line": 2,
                }
            ],
            "metrics": {"overall_latency_ms": 10},
        }


class DummyResponse:
    def __init__(self, content, token_usage):
        self.content = content
        self.token_usage = token_usage


class DummyLLM:
    async def ainvoke(self, messages):
        return DummyResponse("I don't know based on the repository code.", 3)


def test_evaluation_service_computes_report(monkeypatch):
    monkeypatch.setattr("app.services.evaluation_service.HybridRetrievalService", lambda db: DummyHybrid())
    monkeypatch.setattr("app.services.evaluation_service.get_llm", lambda temperature, max_tokens: DummyLLM())

    service = EvaluationService(DummyDB())
    sample_queries = [
        {"query": "How does authentication work?", "relevant_files": ["app.py"], "ground_truth": "Authentication is handled in app.py."}
    ]

    report = asyncio.run(service.evaluate_repository(uuid4(), sample_queries, top_k=1, include_baseline=True))

    assert isinstance(report, EvaluationReport)
    assert report.retrieval.precision_at_k == 1.0
    assert report.retrieval.recall_at_k == 1.0
    assert report.retrieval.mrr == 1.0
    assert report.cost.tokens_used >= 3
    assert report.baseline.total_tokens >= 3
    assert report.comparison["cost_delta_usd"] <= report.cost.cost_usd


def test_evaluation_report_markdown_contains_sections():
    report = EvaluationReport(
        metadata={"repository_id": "repo-123", "sample_count": 1},
        retrieval=type("R", (), {"precision_at_k": 0.5, "recall_at_k": 0.2, "mrr": 0.25})(),
        rag=type("R", (), {"faithfulness": 0.6, "context_precision": 0.7, "context_recall": 0.8, "answer_relevancy": 0.9})(),
        performance=type("P", (), {"retrieval_ms": 12, "llm_latency_ms": 24, "total_ms": 36})(),
        cost=type("C", (), {"tokens_used": 42, "cost_usd": 0.0025})(),
    )
    markdown = report.to_markdown()
    assert "## Retrieval Metrics" in markdown
    assert "## RAG Metrics" in markdown
    assert "## Performance Metrics" in markdown
    assert "## Cost Metrics" in markdown
