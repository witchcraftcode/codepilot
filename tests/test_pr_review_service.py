"""Tests for pull request review orchestration."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.pr_review_comment import PRReviewComment
from app.models.review import Review
from app.services.github_service import PullRequestData
from app.services.pr_review_service import PRReviewService

SAMPLE_DIFF = """diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,3 +1,4 @@
 def login():
+    password = "hardcoded-secret"
     return True
"""


def _make_pr_data() -> PullRequestData:
    return PullRequestData(
        number=7,
        title="Fix auth",
        body="Updates authentication",
        html_url="https://github.com/test/repo/pull/7",
        base_branch="main",
        head_branch="fix-auth",
        state="open",
        diff=SAMPLE_DIFF,
        files=[{"filename": "app/auth.py", "status": "modified"}],
    )


class FakeDB:
    def __init__(self):
        self.added = []
        self._flush_count = 0

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, Review) and not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
        if isinstance(obj, PRReviewComment) and not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    async def flush(self):
        self._flush_count += 1

    async def execute(self, query):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        return result


class TestPRReviewServiceNormalization:
    def test_normalize_finding_with_confidence(self):
        svc = PRReviewService(FakeDB())
        finding = {
            "file_path": "app.py",
            "line_number": 10,
            "severity": "critical",
            "title": "SQL injection",
            "description": "Unsafe query construction",
            "suggestion": "Use parameterized queries",
            "confidence": 0.95,
        }
        normalized = svc._normalize_finding(finding, "security")
        assert normalized is not None
        assert normalized["confidence_score"] == 0.95
        assert normalized["suggested_fix"] == "Use parameterized queries"

    def test_normalize_finding_default_confidence(self):
        svc = PRReviewService(FakeDB())
        finding = {
            "file_path": "app.py",
            "line_number": 5,
            "severity": "high",
            "description": "Performance issue",
            "suggested_optimization": "Use batch queries",
        }
        normalized = svc._normalize_finding(finding, "performance")
        assert normalized is not None
        assert normalized["confidence_score"] == 0.8
        assert normalized["suggested_fix"] == "Use batch queries"

    def test_normalize_finding_missing_line_returns_none(self):
        svc = PRReviewService(FakeDB())
        finding = {"file_path": "app.py", "severity": "low", "description": "No line"}
        assert svc._normalize_finding(finding, "security") is None

    def test_build_comments_deduplicates(self):
        svc = PRReviewService(FakeDB())
        review_id = uuid.uuid4()
        result = {
            "review_id": str(review_id),
            "security_result": {
                "findings": [
                    {
                        "file_path": "app.py",
                        "line_number": 1,
                        "severity": "critical",
                        "title": "Secret",
                        "description": "Hardcoded secret",
                        "suggestion": "Use env vars",
                        "confidence": 0.9,
                    },
                    {
                        "file_path": "app.py",
                        "line_number": 1,
                        "severity": "critical",
                        "title": "Secret",
                        "description": "Duplicate",
                        "suggestion": "Use env vars",
                        "confidence": 0.9,
                    },
                ],
            },
        }
        comments = svc._build_comments(result)
        assert len(comments) == 1
        assert comments[0].severity == "critical"
        assert comments[0].confidence_score == 0.9

    def test_build_comments_orders_by_severity_then_confidence(self):
        svc = PRReviewService(FakeDB())
        review_id = uuid.uuid4()
        result = {
            "review_id": str(review_id),
            "security_result": {
                "findings": [
                    {
                        "file_path": "b.py",
                        "line_number": 10,
                        "severity": "medium",
                        "title": "Medium issue",
                        "description": "Medium confidence issue",
                        "confidence": 0.99,
                    },
                    {
                        "file_path": "a.py",
                        "line_number": 2,
                        "severity": "critical",
                        "title": "Critical issue",
                        "description": "Critical issue",
                        "confidence": 0.7,
                    },
                    {
                        "file_path": "a.py",
                        "line_number": 1,
                        "severity": "high",
                        "title": "High issue",
                        "description": "High confidence issue",
                        "confidence": 0.95,
                    },
                ],
            },
        }
        comments = svc._build_comments(result)
        assert [c.severity for c in comments] == ["critical", "high", "medium"]


class TestPRReviewServicePipeline:
    @pytest.mark.asyncio
    async def test_review_pull_request_full_pipeline(self, monkeypatch):
        db = FakeDB()
        svc = PRReviewService(db)

        pr_data = _make_pr_data()

        async def fake_fetch(self, owner, repo, number):
            return pr_data

        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.fetch_pull_request",
            fake_fetch,
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.parse_repository",
            lambda self, r: ("test", "repo"),
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.PRReviewService._retrieve_repo_context",
            AsyncMock(return_value=[]),
        )

        async def fake_plan(self, state):
            return {
                "agents": [
                    {"name": "security", "priority": 100},
                    {"name": "summary", "priority": 10},
                ],
                "summary": "Run security checks on PR diff",
            }

        async def fake_security_run(self, state):
            chunks = state.get("retrieved_context", [])
            assert chunks, "Expected diff context to be passed to agents"
            assert chunks[0]["file_path"] == "app/auth.py"
            return {
                "agent_name": "security",
                "score": 40,
                "findings": [
                    {
                        "severity": "critical",
                        "file_path": "app/auth.py",
                        "line_number": 2,
                        "title": "Hardcoded secret detected",
                        "description": "Password stored in source code",
                        "suggestion": "Use environment variables",
                        "confidence": 0.95,
                    }
                ],
                "summary": "Critical security issue found",
                "tokens_used": 0,
                "duration_ms": 5,
            }

        async def fake_summarize(self, state, results):
            return {
                "overall_score": 40,
                "summary": "PR has critical security issues that must be fixed before merge.",
                "top_issues": [{"title": "Hardcoded secret", "severity": "critical"}],
                "priority_fixes": [{"action": "Remove hardcoded password"}],
                "roadmap": [],
            }

        import agents.specialized as spec

        monkeypatch.setattr(spec.PlannerAgent, "plan", fake_plan)
        monkeypatch.setattr(spec.SecurityAgent, "run", fake_security_run)
        monkeypatch.setattr(spec.SummaryAgent, "summarize", fake_summarize)

        user_id = uuid.uuid4()
        review, changed_files = await svc.review_pull_request(
            repository="test/repo",
            pull_request_number=7,
            user_id=user_id,
            access_token="ghp_token",
        )

        assert review.status == "completed"
        assert review.pr_number == 7
        assert review.pr_title == "Fix auth"
        assert review.summary is not None
        assert review.overall_score == 40
        assert "security" in (review.agents_executed or [])
        assert changed_files == ["app/auth.py"]

        comment_objects = [o for o in db.added if isinstance(o, PRReviewComment)]
        assert len(comment_objects) >= 1
        comment = comment_objects[0]
        assert comment.file_path == "app/auth.py"
        assert comment.line_number == 2
        assert comment.severity == "critical"
        assert comment.confidence_score == 0.95
        assert comment.suggested_fix == "Use environment variables"

        log_objects = [o for o in db.added if hasattr(o, "agent_name") and getattr(o, "agent_name") == "security"]
        assert len(log_objects) >= 1

    @pytest.mark.asyncio
    async def test_review_pull_request_without_indexed_repo(self, monkeypatch):
        db = FakeDB()
        svc = PRReviewService(db)

        async def fake_fetch(self, owner, repo, number):
            return _make_pr_data()

        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.fetch_pull_request",
            fake_fetch,
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.parse_repository",
            lambda self, r: ("test", "repo"),
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.PRReviewService._retrieve_repo_context",
            AsyncMock(return_value=[]),
        )

        async def fake_plan(self, state):
            return {"agents": [{"name": "summary", "priority": 10}], "summary": "No agents needed"}

        async def fake_summarize(self, state, results):
            return {
                "overall_score": 90,
                "summary": "No issues found in PR diff.",
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
            }

        import agents.specialized as spec

        monkeypatch.setattr(spec.PlannerAgent, "plan", fake_plan)
        monkeypatch.setattr(spec.SummaryAgent, "summarize", fake_summarize)

        review, changed_files = await svc.review_pull_request(
            repository="test/repo",
            pull_request_number=7,
            user_id=uuid.uuid4(),
        )

        assert review.repository_id is None
        assert review.status == "completed"
        assert changed_files == ["app/auth.py"]

    @pytest.mark.asyncio
    async def test_review_pull_request_failure_marks_failed(self, monkeypatch):
        db = FakeDB()
        svc = PRReviewService(db)

        async def fake_fetch(self, owner, repo, number):
            raise RuntimeError("GitHub API down")

        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.fetch_pull_request",
            fake_fetch,
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.parse_repository",
            lambda self, r: ("test", "repo"),
        )

        with pytest.raises(RuntimeError, match="GitHub API down"):
            await svc.review_pull_request(
                repository="test/repo",
                pull_request_number=7,
                user_id=uuid.uuid4(),
            )

        review_objects = [o for o in db.added if isinstance(o, Review)]
        assert len(review_objects) == 0

    @pytest.mark.asyncio
    async def test_review_pull_request_pipeline_failure_persists_failed_review(self, monkeypatch):
        db = FakeDB()
        svc = PRReviewService(db)

        async def fake_fetch(self, owner, repo, number):
            return _make_pr_data()

        async def fake_pipeline(**kwargs):
            raise RuntimeError("agent failed")

        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.fetch_pull_request",
            fake_fetch,
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.GitHubService.parse_repository",
            lambda self, r: ("test", "repo"),
        )
        monkeypatch.setattr(
            "app.services.pr_review_service.PRReviewService._retrieve_repo_context",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(svc, "_run_pipeline", fake_pipeline)

        review, changed_files = await svc.review_pull_request(
            repository="test/repo",
            pull_request_number=7,
            user_id=uuid.uuid4(),
        )

        assert review.status == "failed"
        assert review.summary == "PR review failed: agent failed"
        assert review.completed_at is not None
        assert changed_files == ["app/auth.py"]
