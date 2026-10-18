import asyncio

import httpx
import pytest

from app import main


@pytest.mark.asyncio
async def test_health_is_liveness_and_ready_checks_dependencies(monkeypatch):
    calls = []

    async def healthy():
        calls.append("healthy")

    monkeypatch.setattr(main, "check_postgres_connection", healthy)
    monkeypatch.setattr(main, "check_redis_connection", healthy)
    monkeypatch.setattr(main, "check_qdrant_connection", healthy)
    app = main.create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/health")
        ready = await client.get("/ready")

    assert live.status_code == 200 and live.json() == {"status": "ok"}
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_ready_fails_closed_with_generic_response(monkeypatch):
    async def healthy():
        return None

    async def unavailable():
        raise RuntimeError("sensitive database connection string")

    monkeypatch.setattr(main, "check_postgres_connection", healthy)
    monkeypatch.setattr(main, "check_redis_connection", unavailable)
    monkeypatch.setattr(main, "check_qdrant_connection", healthy)
    app = main.create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/health")
        ready = await client.get("/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}
    assert "sensitive" not in ready.text


@pytest.mark.asyncio
async def test_ready_times_out_within_dependency_bound(monkeypatch):
    async def slow():
        await asyncio.sleep(0.1)

    monkeypatch.setattr(main, "check_postgres_connection", slow)
    monkeypatch.setattr(main, "check_redis_connection", slow)
    monkeypatch.setattr(main, "check_qdrant_connection", slow)
    monkeypatch.setattr(main.get_settings(), "health_check_timeout_seconds", 0.01)
    app = main.create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ready = await client.get("/ready")
    assert ready.status_code == 503
