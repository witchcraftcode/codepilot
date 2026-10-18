import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import session as database_session
from app import main
from app.services import startup


def test_neon_urls_use_asyncpg_and_require_tls():
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgres://user:secret@ep-example-pooler.us-east-2.aws.neon.tech/db"
            "?sslmode=require&channel_binding=require"
        ),
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "ssl=require" in settings.database_url
    assert "sslmode" not in settings.database_url
    assert "channel_binding" not in settings.database_url


def test_neon_url_without_tls_is_upgraded_to_tls():
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:secret@ep-example.us-east-2.aws.neon.tech/db",
    )
    assert "ssl=require" in settings.database_url


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql://user:secret@db.example.com/codepilot",
        "postgresql://user@/",
        "postgresql://user:secret@db.example.com:not-a-port/codepilot",
    ],
)
def test_invalid_database_url_fails_configuration(database_url):
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, database_url=database_url)


def test_neon_url_cannot_disable_tls():
    with pytest.raises(ValidationError, match="Neon URLs must use TLS") as exc_info:
        Settings(
            _env_file=None,
            database_url="postgresql://user:secret@ep-example.neon.tech/db?sslmode=disable",
        )
    assert "secret" not in str(exc_info.value)


def test_database_engine_sets_finite_asyncpg_and_pool_timeouts(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        database_session,
        "create_async_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )
    settings = Settings(_env_file=None, database_connect_timeout_seconds=17)
    database_session.create_database_engine(settings)
    assert captured["connect_args"]["timeout"] == 17
    assert captured["pool_timeout"] == 17
    assert captured["url"].startswith("postgresql+asyncpg://")


@pytest.mark.asyncio
async def test_postgres_connection_check_succeeds(monkeypatch):
    executed = []

    class Connection:
        async def execute(self, statement):
            executed.append(str(statement))

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(startup, "engine", SimpleNamespace(connect=ConnectionContext))
    await startup.check_postgres_connection()
    assert executed == ["SELECT 1"]


@pytest.mark.asyncio
async def test_postgres_connection_failure_is_sanitized(monkeypatch, caplog):
    class FailedEngine:
        def connect(self):
            raise RuntimeError("postgres://user:secret@db.example.com/db")

    monkeypatch.setattr(startup, "engine", FailedEngine())
    with pytest.raises(RuntimeError, match="PostgreSQL startup check failed") as exc_info:
        await startup.check_postgres_connection()
    assert exc_info.value.__cause__ is None
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_startup_times_out_postgres_and_does_not_continue(monkeypatch):
    calls = []

    async def hangs():
        await asyncio.sleep(1)

    async def should_not_run():
        calls.append("later")

    monkeypatch.setattr(
        startup,
        "settings",
        SimpleNamespace(database_connect_timeout_seconds=-4.99, health_check_timeout_seconds=0.01),
    )
    monkeypatch.setattr(startup, "check_postgres_connection", hangs)
    monkeypatch.setattr(startup, "check_redis_connection", should_not_run)
    monkeypatch.setattr(startup, "check_qdrant_connection", should_not_run)

    with pytest.raises(RuntimeError, match="timed out: postgres"):
        await startup.run_startup_checks()
    assert calls == []


@pytest.mark.asyncio
async def test_startup_fails_fast_on_unreachable_postgres_without_logging_url(
    monkeypatch, caplog
):
    async def unreachable():
        raise RuntimeError("postgresql://user:secret@db.example.com/app refused")

    async def should_not_run():
        pytest.fail("startup continued after PostgreSQL failure")

    monkeypatch.setattr(
        startup,
        "settings",
        SimpleNamespace(database_connect_timeout_seconds=1, health_check_timeout_seconds=1),
    )
    monkeypatch.setattr(startup, "check_postgres_connection", unreachable)
    monkeypatch.setattr(startup, "check_redis_connection", should_not_run)
    monkeypatch.setattr(startup, "check_qdrant_connection", should_not_run)

    with pytest.raises(RuntimeError, match="Startup dependency check failed: postgres") as exc_info:
        await startup.run_startup_checks()
    assert exc_info.value.__cause__ is None
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_application_lifespan_does_not_continue_after_startup_failure(monkeypatch):
    async def fail_startup():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "run_startup_checks", fail_startup)
    with pytest.raises(RuntimeError, match="database unavailable"):
        async with main.lifespan(main.app):
            pytest.fail("application entered serving state after database failure")
