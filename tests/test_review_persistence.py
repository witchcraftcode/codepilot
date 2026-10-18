"""Regression tests for reusing the review row created by the API."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.models.review import Review
from app.services import review_service as review_service_module
from app.services.review_service import ReviewService


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_start_review_reuses_existing_id_and_does_not_add_second_review(monkeypatch):
    repository_id = uuid4()
    user_id = uuid4()
    review_id = uuid4()
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        status="ready",
        languages={"Python": 1},
        frameworks=[],
        dependencies={},
        file_count=1,
        health_score=None,
    )
    review = SimpleNamespace(
        id=review_id,
        repository_id=repository_id,
        user_id=user_id,
        status="pending",
    )

    class FakeWorkflow:
        def __init__(self, progress_callback=None):
            self.progress_callback = progress_callback

        async def run(self, state):
            assert state["review_id"] == str(review_id)
            assert db.commit.await_count == 1
            return {
                "overall_score": 82,
                "summary": "Review completed",
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
                "agents_to_run": ["repository", "summary"],
                "repository_result": {
                    "agent_name": "repository",
                    "score": 81,
                    "summary": "Analyzed repository structure.",
                    "findings": [],
                    "tokens_used": 12,
                },
                "total_tokens": 12,
            }

    monkeypatch.setattr(review_service_module, "ReviewWorkflow", FakeWorkflow)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[ScalarResult(repository), ScalarResult(review)]
        ),
        flush=AsyncMock(),
        commit=AsyncMock(),
        add=Mock(),
    )

    result = await ReviewService(db).start_review(
        repository_id,
        user_id,
        review_id=review_id,
    )

    assert result is review
    assert result.id == review_id
    assert result.status == "completed"
    assert result.summary == "Review completed"
    assert db.add.call_count == 2
    assert not isinstance(db.add.call_args.args[0], Review)


@pytest.mark.asyncio
async def test_start_review_skips_duplicate_background_delivery(monkeypatch):
    repository_id, user_id, review_id = uuid4(), uuid4(), uuid4()
    review = SimpleNamespace(
        id=review_id,
        repository_id=repository_id,
        user_id=user_id,
        status="running",
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(SimpleNamespace(
            id=repository_id,
            owner_id=user_id,
            status="ready",
        )), ScalarResult(review)]),
        flush=AsyncMock(),
        add=Mock(),
    )
    result = await ReviewService(db).start_review(
        repository_id, user_id, review_id=review_id
    )
    assert result is review
    assert result.status == "running"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_without_analysis_agent_result_fails_review(monkeypatch):
    repository_id, user_id, review_id = uuid4(), uuid4(), uuid4()
    repo = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        status="ready",
        languages={},
        frameworks=[],
        dependencies={},
        file_count=0,
        health_score=None,
    )
    review = SimpleNamespace(
        id=review_id,
        repository_id=repository_id,
        user_id=user_id,
        status="pending",
    )

    class SummaryOnlyWorkflow:
        def __init__(self, progress_callback=None):
            pass

        async def run(self, state):
            return {
                "agents_to_run": ["summary"],
                "overall_score": 50,
                "summary": "Review completed.",
                "total_tokens": 0,
            }

    monkeypatch.setattr(review_service_module, "ReviewWorkflow", SummaryOnlyWorkflow)
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(repo), ScalarResult(review)]),
        flush=AsyncMock(),
        commit=AsyncMock(),
        add=Mock(),
    )
    with pytest.raises(RuntimeError, match="without an analysis agent result"):
        await ReviewService(db).start_review(repository_id, user_id, review_id=review_id)
    assert review.status == "failed"
    assert review.completed_at is not None
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_stale_recovery_only_targets_old_pending_rows():
    result = SimpleNamespace(rowcount=2)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    assert await ReviewService.fail_abandoned_pending_reviews(db) == 2
    statement = str(db.execute.await_args.args[0]).lower()
    assert "reviews.status in" in statement
    assert "reviews.created_at <" in statement
    assert "running" not in statement


@pytest.mark.asyncio
async def test_stale_recovery_can_fail_interrupted_running_rows():
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
    assert await ReviewService.fail_abandoned_pending_reviews(db, include_running=True) == 1
    statement = db.execute.await_args.args[0]
    params = str(statement.compile().params.values()).lower()
    assert "running" in params
    assert "interrupted" in params
