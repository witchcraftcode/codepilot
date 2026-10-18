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
            return {
                "overall_score": 82,
                "summary": "Review completed",
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
                "agents_to_run": ["summary"],
                "total_tokens": 0,
            }

    monkeypatch.setattr(review_service_module, "ReviewWorkflow", FakeWorkflow)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[ScalarResult(repository), ScalarResult(review)]
        ),
        flush=AsyncMock(),
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
    assert db.add.call_count == 1
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
async def test_stale_recovery_only_targets_old_pending_rows():
    result = SimpleNamespace(rowcount=2)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    assert await ReviewService.fail_abandoned_pending_reviews(db) == 2
    statement = str(db.execute.await_args.args[0]).lower()
    assert "reviews.status = :status_1" in statement
    assert "reviews.created_at <" in statement
    assert "running" not in statement
