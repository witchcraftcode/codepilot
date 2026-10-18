import asyncio
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import startup


class FakeAsyncQdrantClient:
    default_impl = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.collection_names = []
        self.close_calls = 0
        self.get_collection_impl = type(self).default_impl

    async def get_collection(self, collection_name):
        self.collection_names.append(collection_name)
        if self.get_collection_impl:
            return await self.get_collection_impl()
        return {"status": "ok"}

    async def close(self):
        self.close_calls += 1


@pytest.fixture
def fake_qdrant(monkeypatch):
    clients = []
    FakeAsyncQdrantClient.default_impl = None

    def factory(**kwargs):
        client = FakeAsyncQdrantClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setitem(sys.modules, "qdrant_client", SimpleNamespace(AsyncQdrantClient=factory))
    monkeypatch.setattr(
        startup,
        "settings",
        SimpleNamespace(
            qdrant_url="https://qdrant.example.invalid",
            qdrant_api_key="test-key",
            qdrant_collection="codepilot_chunks",
            startup_dependency_timeout_seconds=10,
        ),
    )
    return clients


def test_startup_dependency_timeout_is_configurable_and_bounded():
    settings = Settings(_env_file=None, startup_dependency_timeout_seconds=25)
    assert settings.startup_dependency_timeout_seconds == 25
    for value in (0, 61):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, startup_dependency_timeout_seconds=value)


@pytest.mark.asyncio
async def test_qdrant_fast_success_uses_configured_async_client_and_collection(fake_qdrant):
    await startup.check_qdrant_connection()
    client = fake_qdrant[0]
    assert client.kwargs == {
        "url": "https://qdrant.example.invalid",
        "api_key": "test-key",
        "timeout": 10,
        "check_compatibility": False,
    }
    assert client.collection_names == ["codepilot_chunks"]
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_qdrant_slow_response_can_complete_within_configured_bound(fake_qdrant):
    async def slow_response():
        await asyncio.sleep(0.02)

    FakeAsyncQdrantClient.default_impl = slow_response
    await asyncio.wait_for(startup.check_qdrant_connection(), timeout=0.2)
    assert fake_qdrant[0].close_calls == 1


@pytest.mark.asyncio
async def test_qdrant_timeout_cancels_request_and_closes_client(monkeypatch, fake_qdrant):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_response():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    FakeAsyncQdrantClient.default_impl = slow_response
    task = asyncio.create_task(startup.check_qdrant_connection())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert fake_qdrant[0].close_calls == 1


@pytest.mark.asyncio
async def test_startup_outer_timeout_cancels_qdrant_check_and_fails(monkeypatch):
    cancellation_seen = asyncio.Event()
    async def healthy():
        return None

    async def hanging_qdrant():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            raise

    monkeypatch.setattr(
        startup,
        "settings",
        SimpleNamespace(database_connect_timeout_seconds=1, startup_dependency_timeout_seconds=0.01),
    )
    monkeypatch.setattr(startup, "check_postgres_connection", healthy)
    monkeypatch.setattr(startup, "check_redis_connection", healthy)
    monkeypatch.setattr(startup, "check_qdrant_connection", hanging_qdrant)
    with pytest.raises(RuntimeError, match="timed out: qdrant"):
        await startup.run_startup_checks()
    assert cancellation_seen.is_set()


@pytest.mark.asyncio
async def test_qdrant_connection_failure_is_sanitized_and_not_reported_success(
    fake_qdrant, caplog
):
    async def fail():
        raise OSError("request to https://user:secret@qdrant.example.invalid failed")

    FakeAsyncQdrantClient.default_impl = fail
    # The client is instantiated when the check coroutine starts.
    with pytest.raises(RuntimeError, match="Qdrant connection failure") as exc_info:
        await startup.check_qdrant_connection()
    assert exc_info.value.__cause__ is None
    assert fake_qdrant[0].close_calls == 1
    assert "secret" not in caplog.text
