"""Regression coverage for API ownership and score integrity."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.api.routes.chat import get_scores, submit_feedback
from app.api.routes.review import _require_owned_repository
from app.main import _request_route_label
from app.schemas import FeedbackCreate
from fastapi import HTTPException


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_metrics_use_route_template_instead_of_resource_id():
    request = SimpleNamespace(
        scope={
            "route": SimpleNamespace(path="/api/v1/review/{review_id}"),
        },
        url=SimpleNamespace(path="/api/v1/review/secret-resource-id"),
    )

    assert _request_route_label(request) == "/api/v1/review/{review_id}"


@pytest.mark.asyncio
async def test_repository_guard_hides_resources_owned_by_another_user():
    db = SimpleNamespace(execute=AsyncMock(return_value=ScalarResult(None)))

    with pytest.raises(HTTPException) as exc_info:
        await _require_owned_repository(db, uuid4(), uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_feedback_rejects_review_owned_by_another_user():
    db = SimpleNamespace(
        execute=AsyncMock(return_value=ScalarResult(None)), add=Mock()
    )
    user = SimpleNamespace(id=uuid4())
    body = FeedbackCreate(
        review_id=uuid4(),
        finding_id="finding-1",
        agent_name="security",
        accepted=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await submit_feedback(body, db, user)

    assert exc_info.value.status_code == 404
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_scores_without_completed_review_are_unknown_not_fabricated():
    repository_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    repository = SimpleNamespace(id=repository_id, health_score=None)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[ScalarResult(repository), ScalarResult(None)]
        )
    )

    response = await get_scores(repository_id, db, user)

    assert response.health_score.model_dump() == {
        "security": None,
        "performance": None,
        "architecture": None,
        "documentation": None,
        "testing": None,
        "maintainability": None,
        "overall": None,
    }
    assert response.last_review_at is None


@pytest.mark.asyncio
async def test_scores_preserve_actual_zero_values():
    repository_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    review_time = datetime.now(timezone.utc)
    review = SimpleNamespace(id=uuid4(), overall_score=0, completed_at=review_time)
    report = SimpleNamespace(
        security={"score": 0},
        performance={"score": 61},
        architecture=None,
        documentation=None,
        testing=None,
        style={"score": 74},
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                ScalarResult(SimpleNamespace(id=repository_id, health_score=None)),
                ScalarResult(review),
                ScalarResult(report),
            ]
        )
    )

    response = await get_scores(repository_id, db, user)

    assert response.health_score.security == 0
    assert response.health_score.performance == 61
    assert response.health_score.architecture is None
    assert response.health_score.maintainability == 74
    assert response.health_score.overall == 0
    assert response.last_review_at is review_time
