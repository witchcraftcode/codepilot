import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.routes import review as review_route
from app import main
from app.models.review import Review


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_background_worker_marks_cancelled_review_failed(monkeypatch):
    review_id = uuid4()
    review = SimpleNamespace(status="running", completed_at=None, summary=None)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=Result(review)),
        commit=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    class FakeEngine:
        dispose = AsyncMock()

    fake_engine = FakeEngine()
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", lambda url: fake_engine
    )
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.async_sessionmaker", lambda *args, **kwargs: SessionContext
    )

    class CancelledService:
        def __init__(self, db):
            pass

        async def start_review(self, *args, **kwargs):
            raise asyncio.CancelledError

    monkeypatch.setattr(review_route, "ReviewService", CancelledService)
    with pytest.raises(asyncio.CancelledError):
        await review_route._run_review_background(
            review_id, uuid4(), uuid4(), "full", "postgresql+asyncpg://db/test", None, None
        )

    assert review.status == "failed"
    assert review.completed_at is not None
    assert review.summary == "Review interrupted because the worker stopped. Please retry."
    session.commit.assert_awaited_once()
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_review_schedules_process_local_background_task(monkeypatch):
    repository_id, user_id = uuid4(), uuid4()
    repository = SimpleNamespace(id=repository_id)

    class Db:
        commit = AsyncMock()

        def add(self, review):
            self.review = review

        async def flush(self):
            self.review.id = uuid4()

        async def execute(self, query):
            return Result(repository)

    class BackgroundTasks:
        def add_task(self, fn, *args):
            assert db.commit.await_count == 1
            self.call = (fn, args)

    db = Db()

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://db/test"),
    )
    background = BackgroundTasks()
    response = await review_route.create_review(
        review_route.ReviewCreate(repository_id=repository_id, review_type="full"),
        background,
        db,
        SimpleNamespace(id=user_id),
    )
    fn, args = background.call
    assert fn is review_route._run_review_background
    assert args[0] == response.id
    assert response.status == "pending"


@pytest.mark.asyncio
async def test_periodic_recovery_checks_stranded_pending_reviews(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: SessionContext())
    recovery = AsyncMock(return_value=1)
    monkeypatch.setattr(main.ReviewService, "fail_abandoned_pending_reviews", recovery)

    sleeps = 0

    async def one_iteration_then_cancel(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, "sleep", one_iteration_then_cancel)
    with pytest.raises(asyncio.CancelledError):
        await main._review_recovery_loop()
    recovery.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()
